import re
import uuid
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from pydantic import BaseModel

try:
    from .models import Memory
    from .schemas import CandidateMemory
except ImportError:
    from models import Memory
    from schemas import CandidateMemory


# -----------------------------------------------------------------------------
# Sensitive / Secret Patterns
# -----------------------------------------------------------------------------
SENSITIVE_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|token|auth[_-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{8,}['\"]?", re.IGNORECASE),
    re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{4,}['\"]?", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
]

GREETING_TOKENS = {
    "hi", "hello", "hey", "good", "morning", "afternoon", "evening", "night",
    "howdy", "greetings", "sup", "yo", "thanks", "thank", "you", "so", "much",
    "great", "job", "awesome", "ok", "okay", "cool", "got", "it", "sounds",
    "fine", "welcome", "bye", "goodbye", "see", "later", "please", "yes", "no",
    "yep", "nope", "sure", "alright", "all", "right", "there", "doing", "today",
    "how", "are", "is", "it", "going", "what", "whats", "what's", "up"
}

UNCERTAINTY_PATTERN = re.compile(
    r"\b(?:maybe|might|perhaps|not\s+sure\s+if|uncertain|possibly|could\s+be|don't\s+know\s+if)\b",
    re.IGNORECASE,
)
TEMPORARY_FEELING_PATTERN = re.compile(
    r"\b(?:feeling|hungry|tired|sleepy|thirsty|bored|right\s+now|at\s+the\s+moment|today\s+only)\b",
    re.IGNORECASE,
)


def contains_secrets(text: str) -> bool:
    """Detect passwords, tokens, or API keys in text."""
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


def is_greeting_or_filler(text: str) -> bool:
    """Detect conversational greetings, thanks, and fillers."""
    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())
    if not words:
        return True
    greeting_count = sum(1 for w in words if w.replace("'", "") in GREETING_TOKENS)
    return (greeting_count / len(words)) >= 0.70


def normalize_tokens(text: str) -> set:
    """Extract lowercased alphanumeric words excluding minor stop words."""
    stop_words = {
        "a", "an", "the", "is", "am", "are", "was", "were", "i", "im", "i'm",
        "and", "to", "for", "with", "of", "in", "on", "at", "my", "me", "using",
        "project", "system"
    }
    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
    return {w for w in words if w not in stop_words}


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate token Jaccard similarity between two texts."""
    t1, t2 = text1.lower().strip(), text2.lower().strip()
    if t1 == t2:
        return 1.0

    tokens1 = normalize_tokens(t1)
    tokens2 = normalize_tokens(t2)
    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


# -----------------------------------------------------------------------------
# Base Extraction Provider Interface
# -----------------------------------------------------------------------------
class BaseExtractionProvider(ABC):
    """
    Abstract interface for memory extraction providers.
    Allows swappable implementations (e.g. Deterministic in Phase 3 -> LLM in Phase 5).
    """

    @abstractmethod
    def extract_candidates(
        self,
        message: str,
        existing_memories: List[Memory],
        user_id: str = "default_user",
    ) -> List[CandidateMemory]:
        """Extract candidate memories from user message compared against existing memories."""
        pass


# -----------------------------------------------------------------------------
# Deterministic Development Extractor Implementation
# -----------------------------------------------------------------------------
class DeterministicExtractorProvider(BaseExtractionProvider):
    """
    Deterministic rule-based extraction service.
    Classifies durable facts, detects categories, filters secrets/greetings,
    and assigns actions (create, update, duplicate, conflict).
    """

    def __init__(self):
        self.provider_name = "deterministic_v1"

    def split_clauses(self, text: str) -> List[str]:
        """Splits composite messages into logical statement clauses."""
        text = text.strip()
        parts = re.split(r"(?<=[.!?])\s+|\s+and\s+(?=[a-zA-Z0-9'\"])|;\s*", text, flags=re.IGNORECASE)
        clauses = []
        for p in parts:
            p_clean = p.strip().strip(".?!,;").strip()
            if p_clean and len(p_clean) >= 4:
                clauses.append(p_clean)
        return clauses

    def classify_clause(self, clause: str) -> Tuple[Optional[str], Optional[str], Optional[str], float, bool]:
        """
        Classifies clause into (title, content, category, confidence, is_durable).
        Returns None for category if no durable fact is identified.
        """
        lower = clause.lower()

        # 1. Filter out greetings, filler, transient feelings
        if is_greeting_or_filler(clause):
            return None, None, None, 0.0, False

        if UNCERTAINTY_PATTERN.search(clause) or TEMPORARY_FEELING_PATTERN.search(clause):
            return None, None, None, 0.2, False

        # 2. Skills and Learning Goals
        skill_match = re.search(
            r"(?:i'm\s+learning|i\s+am\s+learning|learning|studying|mastering|practicing|skilled\s+in|proficient\s+in)\s+([^,.!?]+)",
            lower,
        )
        if skill_match:
            subject = skill_match.group(1).strip().title()
            title = f"Learning {subject}" if not subject.lower().startswith("learning") else subject
            content = f"Learning and developing proficiency in {subject}."
            return title, content, "Skills", 0.95, True

        # 3. Projects and Ongoing Work
        project_match = re.search(
            r"(?:building|working\s+on|developing|creating|designing|architecting)\s+(?:a\s+|an\s+|the\s+)?([^,.!?]+)",
            lower,
        )
        if project_match:
            proj = project_match.group(1).strip()
            title_text = re.sub(r"\s+using\s+.*", "", proj, flags=re.IGNORECASE).strip().title()
            title = f"{title_text} Project" if not title_text.lower().endswith("project") else title_text
            content = f"Working on {proj}."
            return title, content, "Projects", 0.92, True

        # 4. Personal Preferences (Dietary, Workflows, Habits)
        if re.search(r"\b(?:vegetarian|vegan|pescatarian|gluten[ -]free|reduced sugar|low sugar)\b", lower):
            diet = "Vegetarian" if "vegetarian" in lower else "Vegan" if "vegan" in lower else "Dietary Preference"
            title = f"{diet} Diet"
            content = f"Follows a {lower.strip()} dietary preference."
            return title, content, "Preferences", 0.90, True

        pref_match = re.search(
            r"(?:i\s+prefer|prefer|preference\s+for|routine\s+is|habit\s+is)\s+([^,.!?]+)",
            lower,
        )
        if pref_match:
            pref = pref_match.group(1).strip()
            title = f"Preference: {pref[:30].title()}"
            content = f"Prefers {pref}."
            return title, content, "Preferences", 0.88, True

        # 5. Important Decisions
        decision_match = re.search(
            r"(?:decided\s+to|chose\s+to|agreed\s+to|committed\s+to|concluded\s+that)\s+([^,.!?]+)",
            lower,
        )
        if decision_match:
            decision = decision_match.group(1).strip()
            title = f"Decision: {decision[:30].title()}"
            content = f"Decided to {decision}."
            return title, content, "Decisions", 0.87, True

        # 6. Context & Background (location, education, identity)
        context_match = re.search(
            r"(?:studying\s+at|based\s+in|living\s+in|student\s+at|role\s+is|working\s+at)\s+([^,.!?]+)",
            lower,
        )
        if context_match:
            ctx = context_match.group(1).strip()
            title = f"Location / Affiliation: {ctx[:30].title()}"
            content = f"Associated with {ctx}."
            return title, content, "Context", 0.85, True

        # Fallback for concise declarative facts
        if len(clause.split()) >= 3 and not lower.endswith("?") and not is_greeting_or_filler(clause):
            return clause[:40].title(), clause, "General", 0.65, True

        return None, None, None, 0.0, False

    def evaluate_against_existing(
        self,
        candidate_title: str,
        candidate_content: str,
        category: str,
        existing_memories: List[Memory],
    ) -> Tuple[str, Optional[int], str]:
        """
        Compares candidate fact against existing memories.
        Returns (action, existing_memory_id, explanation)
        action: 'duplicate' | 'update' | 'conflict' | 'create'
        """
        for mem in existing_memories:
            title_sim = calculate_similarity(candidate_title, mem.title)
            content_sim = calculate_similarity(candidate_content, mem.content)

            # 1. Exact or near-identical duplicate on content/title
            if content_sim >= 0.80 or (title_sim >= 0.85 and content_sim >= 0.65):
                return (
                    "duplicate",
                    mem.id,
                    f"Identical or near-identical fact already exists as Memory #{mem.id} ('{mem.title}').",
                )

            # 2. Same topic / category with moderate overlap -> Update or Conflict
            if mem.category.lower() == category.lower() and (title_sim >= 0.40 or content_sim >= 0.35):
                cand_lower = candidate_content.lower()
                has_conflict = any(
                    word in cand_lower
                    for word in ["no longer", "stopped", "switched from", "instead of", "not anymore", "abandoned"]
                )
                if has_conflict:
                    return (
                        "conflict",
                        mem.id,
                        f"Potential contradiction with Memory #{mem.id} ('{mem.title}'). Requires user verification.",
                    )
                return (
                    "update",
                    mem.id,
                    f"Related to existing Memory #{mem.id} ('{mem.title}'). Proposed as an update.",
                )

        return ("create", None, "New unique durable fact.")

    def extract_candidates(
        self,
        message: str,
        existing_memories: List[Memory],
        user_id: str = "default_user",
    ) -> List[CandidateMemory]:
        """
        Extracts candidate memories from message.
        """
        if contains_secrets(message):
            return []

        clauses = self.split_clauses(message)
        candidates: List[CandidateMemory] = []
        seen_titles = set()

        for clause in clauses:
            title, content, category, confidence, is_durable = self.classify_clause(clause)
            if not category or not is_durable or confidence < 0.60:
                continue

            if title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            action, existing_id, explanation = self.evaluate_against_existing(
                title, content, category, existing_memories
            )

            candidate = CandidateMemory(
                candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
                user_id=user_id,
                title=title,
                content=content,
                category=category,
                confidence=round(confidence, 2),
                is_durable=is_durable,
                action=action,
                existing_memory_id=existing_id,
                explanation=explanation,
                source="conversation_extraction",
            )
            candidates.append(candidate)

        return candidates


_extractor_instance: BaseExtractionProvider = DeterministicExtractorProvider()


def get_extractor() -> BaseExtractionProvider:
    """Dependency / accessor for the active extraction provider."""
    return _extractor_instance
