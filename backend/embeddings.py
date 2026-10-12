import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set
import numpy as np


class BaseEmbeddingProvider(ABC):
    """
    Abstract Base Class for embedding providers.
    Enables future plug-in of NVIDIA, Nebius, or cloud embedding models.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """The dimensionality of the produced embedding vectors."""
        pass

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Generate a dense embedding vector for a single text."""
        pass

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        return [self.embed_text(t) for t in texts]


class LocalSemanticEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local deterministic semantic embedding provider for development on Windows.
    Combines feature hashing, subword n-grams, and semantic concept clustering
    to project text into a normalized 128-dimensional dense vector space.
    """

    def __init__(self, dim: int = 128, max_cache_size: int = 2048):
        self._dim = dim
        self.provider_name = "local_semantic_v1"
        self._max_cache_size = max_cache_size
        self._cache: Dict[str, List[float]] = {}
        self.cache_hits: int = 0
        self.cache_misses: int = 0

        # Domain concept clusters for semantic association (e.g. hardware <-> ESP32, sensors)
        self.semantic_clusters: Dict[str, Set[str]] = {
            "hardware": {"hardware", "esp32", "sensor", "sensors", "microcontroller", "iot", "device", "turbidity", "arduino", "board"},
            "software": {"software", "python", "code", "programming", "react", "nextjs", "fastapi", "c++", "sql", "api", "backend", "frontend"},
            "learning": {"learn", "learning", "study", "studying", "skill", "skills", "master", "mastering", "practice", "practicing"},
            "projects": {"project", "projects", "build", "building", "develop", "developing", "work", "working", "create", "initiative", "monitor", "monitoring"},
            "water_monitoring": {"water", "quality", "monitoring", "monitor", "turbidity", "sensors", "temperature", "oxygen", "clean"},
            "diet_health": {"diet", "food", "meal", "eating", "vegetarian", "vegan", "sugar", "calories", "nutrition", "workout", "fitness"},
            "location": {"location", "live", "living", "based", "chennai", "campus", "university", "college", "residence"},
        }

    def clear_cache(self) -> None:
        """Clears the embedding vector cache."""
        self._cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """Returns cache metrics."""
        total = self.cache_hits + self.cache_misses
        hit_ratio = (self.cache_hits / total) if total > 0 else 0.0
        return {
            "cached_entries": len(self._cache),
            "max_cache_size": self._max_cache_size,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_ratio": round(hit_ratio, 4),
        }

    @property
    def dimension(self) -> int:
        return self._dim

    def _tokenize(self, text: str) -> List[str]:
        """Extract alphanumeric tokens."""
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        return [w for w in clean.split() if len(w) >= 2]

    def embed_text(self, text: str) -> List[float]:
        """Compute a normalized 128-dimensional dense semantic embedding with caching."""
        if not text or not text.strip():
            return [0.0] * self._dim

        cache_key = text.strip()
        if cache_key in self._cache:
            self.cache_hits += 1
            return self._cache[cache_key]

        self.cache_misses += 1
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self._dim

        vec = np.zeros(self._dim, dtype=np.float32)

        # 1. Feature hashing for vocabulary tokens & char 3-grams
        for tok in tokens:
            # Word level hashing
            h_val = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h_val % (self._dim // 2)
            sign = 1.0 if ((h_val >> 16) & 1) == 0 else -1.0
            vec[idx] += sign * 1.5

            # Subword 3-grams for morphological similarity
            if len(tok) >= 4:
                for i in range(len(tok) - 2):
                    sub = tok[i:i + 3]
                    h_sub = int(hashlib.md5(sub.encode("utf-8")).hexdigest(), 16)
                    idx_sub = (h_sub % (self._dim // 2))
                    vec[idx_sub] += 0.4

        # 2. Semantic concept cluster activations (dimensions 64 to 127)
        offset = self._dim // 2
        for c_idx, (cluster_name, cluster_words) in enumerate(self.semantic_clusters.items()):
            overlap = sum(1 for tok in tokens if tok in cluster_words)
            if overlap > 0:
                cluster_pos = offset + (c_idx * 6) % (self._dim - offset)
                weight = 2.0 * float(overlap)
                vec[cluster_pos] += weight
                if cluster_pos + 1 < self._dim:
                    vec[cluster_pos + 1] += weight * 0.8

        # 3. L2 Normalization so dot product equals cosine similarity
        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm

        res = vec.tolist()
        if len(self._cache) < self._max_cache_size:
            self._cache[cache_key] = res
        return res


_default_embedding_provider: BaseEmbeddingProvider = LocalSemanticEmbeddingProvider()


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Returns the configured embedding provider."""
    return _default_embedding_provider
