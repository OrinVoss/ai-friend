"""FactChecker: contradiction detection + confidence management for #6.

Detects when newly extracted facts contradict existing ones using
embedding similarity + keyword overlap, then adjusts confidence accordingly.
"""

import logging
from typing import Optional

from models.memory import UserFact

logger = logging.getLogger(__name__)

# Thresholds
SIMILARITY_THRESHOLD = 0.65       # embedding cosine similarity to flag as "same topic"
CONTRADICTION_DECAY = 0.4         # multiply old confidence by this when contradicted
MIN_CONFIDENCE_FILTER = 0.2       # facts below this confidence are suppressed


class FactChecker:
    """Detects and resolves contradictions between facts."""

    def __init__(self, embedding_engine=None):
        self._embed = embedding_engine

    def detect_contradiction(
        self,
        new_fact: UserFact,
        existing_facts: list[UserFact],
    ) -> Optional[UserFact]:
        """Check if a new fact semantically contradicts any existing fact.

        Returns the most likely contradictory fact, or None.
        """
        if not existing_facts:
            return None

        # First pass: same category + same fact_key -> direct contradiction (different value)
        for f in existing_facts:
            if f.category == new_fact.category and f.fact_key == new_fact.fact_key:
                if f.fact_value.strip() != new_fact.fact_value.strip():
                    logger.info(
                        f"[fact_check] direct contradiction: "
                        f"{new_fact.fact_key} = '{f.fact_value}' vs '{new_fact.fact_value}'"
                    )
                    return f

        # Second pass: embedding-based semantic similarity check
        if self._embed and self._embed.health_check():
            new_text = f"{new_fact.category} {new_fact.fact_key} {new_fact.fact_value}"
            try:
                new_vec = self._embed.encode([new_text])[0]
                best_sim = 0.0
                best_match = None
                for f in existing_facts:
                    old_text = f"{f.category} {f.fact_key} {f.fact_value}"
                    old_vec = self._embed.encode([old_text])[0]
                    sim = self._cosine_sim(new_vec, old_vec)
                    if sim > best_sim and sim > SIMILARITY_THRESHOLD:
                        # Check if values differ meaningfully
                        if f.fact_value.strip() != new_fact.fact_value.strip():
                            best_sim = sim
                            best_match = f
                if best_match:
                    logger.info(
                        f"[fact_check] semantic contradiction sim={best_sim:.2f}: "
                        f"'{best_match.fact_key}': '{best_match.fact_value}' vs '{new_fact.fact_value}'"
                    )
                    return best_match
            except Exception as e:
                logger.debug(f"[fact_check] embedding comparison failed: {e}")

        return None

    def resolve(
        self,
        new_fact: UserFact,
        old_fact: UserFact,
        repo,
    ) -> bool:
        """Resolve a contradiction: lower old fact confidence, log the conflict.

        Returns True if old fact was deactivated (confidence too low).
        """
        new_conf = old_fact.confidence * CONTRADICTION_DECAY
        if new_conf < MIN_CONFIDENCE_FILTER:
            logger.warning(
                f"[fact_check] deactivating fact #{old_fact.id}: "
                f"'{old_fact.fact_key} = {old_fact.fact_value}' "
                f"contradicted by '{new_fact.fact_key} = {new_fact.fact_value}'"
            )
            repo.deactivate_fact(old_fact.id)
            return True
        else:
            logger.info(
                f"[fact_check] decaying fact #{old_fact.id} confidence: "
                f"{old_fact.confidence:.2f} -> {new_conf:.2f} "
                f"(contradicted by '{new_fact.fact_key} = {new_fact.fact_value}')"
            )
            repo.update_fact_confidence(old_fact.id, new_conf)
            return False

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
