import json
import re
from typing import List, Optional, Tuple
import faiss
import numpy as np
from sqlalchemy.orm import Session

try:
    from .embeddings import get_embedding_provider
    from .models import Memory, MemoryEmbedding
except ImportError:
    from embeddings import get_embedding_provider
    from models import Memory, MemoryEmbedding


class VectorIndexManager:
    """
    Manages local FAISS vector indexing with SQLite persistence.
    Uses IndexIDMap2 wrapping IndexFlatIP for exact cosine similarity searches.
    """

    def __init__(self):
        self.embedding_provider = get_embedding_provider()
        self.dim = self.embedding_provider.dimension
        self._init_faiss_index()

    def _init_faiss_index(self):
        """Initializes empty FAISS index."""
        base_index = faiss.IndexFlatIP(self.dim)
        self.index = faiss.IndexIDMap2(base_index)

    def index_memory(self, memory_id: int, user_id: str, text: str, db: Session) -> List[float]:
        """
        Embeds memory text, updates the FAISS index, and persists the vector in SQLite.
        """
        vector = self.embedding_provider.embed_text(text)
        vec_np = np.array([vector], dtype=np.float32)
        id_np = np.array([memory_id], dtype=np.int64)

        # 1. Update FAISS Index (remove existing ID if present, then add)
        try:
            self.index.remove_ids(id_np)
        except Exception:
            pass
        self.index.add_with_ids(vec_np, id_np)

        # 2. Persist in SQLite
        existing_emb = db.query(MemoryEmbedding).filter(MemoryEmbedding.memory_id == memory_id).first()
        vec_json = json.dumps(vector)

        if existing_emb:
            existing_emb.embedding_json = vec_json
            existing_emb.user_id = user_id
        else:
            new_emb = MemoryEmbedding(
                memory_id=memory_id,
                user_id=user_id,
                embedding_json=vec_json,
            )
            db.add(new_emb)

        db.commit()
        return vector

    def remove_memory(self, memory_id: int, db: Session) -> bool:
        """
        Removes vector from FAISS index and deletes SQLite embedding record.
        """
        id_np = np.array([memory_id], dtype=np.int64)
        try:
            self.index.remove_ids(id_np)
        except Exception:
            pass

        existing_emb = db.query(MemoryEmbedding).filter(MemoryEmbedding.memory_id == memory_id).first()
        if existing_emb:
            db.delete(existing_emb)
            db.commit()
            return True
        return False

    def remove_user_memories(self, user_id: str, db: Session) -> int:
        """
        Removes all vectors belonging to user_id from the FAISS index and database.
        """
        user_embs = db.query(MemoryEmbedding).filter(MemoryEmbedding.user_id == user_id).all()
        if not user_embs:
            return 0
        ids_np = np.array([emb.memory_id for emb in user_embs], dtype=np.int64)
        try:
            self.index.remove_ids(ids_np)
        except Exception:
            pass
        count = len(user_embs)
        for emb in user_embs:
            db.delete(emb)
        db.commit()
        return count

    def load_or_sync_from_db(self, db: Session):
        """
        Initializes FAISS index from all existing memories in SQLite.
        Ensures missing embeddings are generated.
        """
        self._init_faiss_index()
        all_memories = db.query(Memory).all()
        if not all_memories:
            return

        vectors: List[List[float]] = []
        ids: List[int] = []

        for mem in all_memories:
            emb_record = db.query(MemoryEmbedding).filter(MemoryEmbedding.memory_id == mem.id).first()
            if emb_record:
                vec = json.loads(emb_record.embedding_json)
            else:
                combined_text = f"{mem.title} {mem.content}"
                vec = self.embedding_provider.embed_text(combined_text)
                db.add(MemoryEmbedding(
                    memory_id=mem.id,
                    user_id=mem.user_id,
                    embedding_json=json.dumps(vec),
                ))

            vectors.append(vec)
            ids.append(mem.id)

        db.commit()

        if vectors:
            vec_np = np.array(vectors, dtype=np.float32)
            id_np = np.array(ids, dtype=np.int64)
            self.index.add_with_ids(vec_np, id_np)

    def search(
        self,
        query: str,
        user_id: str,
        db: Session,
        threshold: float = 0.3,
        limit: int = 5,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Tuple[Memory, float]]:
        """
        Performs semantic search with optional category and keyword filtering.
        Returns sorted list of (Memory, similarity_score).
        """
        if self.index.ntotal == 0:
            return []

        query_vec = self.embedding_provider.embed_text(query)
        q_np = np.array([query_vec], dtype=np.float32)

        # Retrieve more candidates from FAISS to allow for user/category filtering
        k_search = min(max(limit * 4, 10), self.index.ntotal)
        scores, ids = self.index.search(q_np, k_search)

        matches: List[Tuple[Memory, float]] = []

        if len(ids) == 0 or len(ids[0]) == 0:
            return []

        for score, mem_id in zip(scores[0], ids[0]):
            score_float = float(score)
            if mem_id < 0 or score_float < threshold:
                continue

            # Verify memory exists, belongs to user, and is not deleted
            memory = db.query(Memory).filter(
                Memory.id == int(mem_id),
                Memory.user_id == user_id,
            ).first()

            if not memory:
                continue

            # Category filter
            if category and memory.category.lower() != category.lower():
                continue

            # Keyword filter
            if keyword:
                kw = keyword.lower()
                if kw not in memory.title.lower() and kw not in memory.content.lower():
                    continue

            matches.append((memory, round(score_float, 4)))

        # Sort descending by score and slice to limit
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]

    def keyword_search(
        self,
        query: str,
        user_id: str,
        db: Session,
        limit: int = 5,
        category: Optional[str] = None,
    ) -> List[Tuple[Memory, float]]:
        """
        Pure keyword-based baseline search for comparison against semantic retrieval.
        Scores memories based on token overlap (term frequency).
        """
        tokens = [w.lower() for w in re.sub(r"[^a-zA-Z0-9\s]", " ", query).split() if len(w) >= 2]
        if not tokens:
            return []

        user_memories = db.query(Memory).filter(Memory.user_id == user_id).all()
        scored: List[Tuple[Memory, float]] = []

        for mem in user_memories:
            if category and mem.category.lower() != category.lower():
                continue

            text = f"{mem.title} {mem.content}".lower()
            matches_count = sum(1 for tok in tokens if tok in text)
            if matches_count > 0:
                score = round(matches_count / len(tokens), 4)
                scored.append((mem, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]


_vector_index_instance: Optional[VectorIndexManager] = None


def get_vector_index() -> VectorIndexManager:
    """Singleton accessor for VectorIndexManager."""
    global _vector_index_instance
    if _vector_index_instance is None:
        _vector_index_instance = VectorIndexManager()
    return _vector_index_instance
