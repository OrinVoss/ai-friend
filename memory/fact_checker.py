"""FactChecker: contradiction detection + confidence management for #6.

Detects when newly extracted facts contradict existing ones using
embedding similarity + keyword overlap, then adjusts confidence accordingly.

Improvements (#254):
- FC-003: validate new-fact quality before resolving contradictions.
- FC-004: use numpy for cosine similarity (vectorised batch comparison).
- FC-005: keyword-overlap semantic fallback when embedding is unavailable.
"""

import logging
import re
from typing import Optional

import numpy as np

from models.memory import UserFact

logger = logging.getLogger(__name__)

# Thresholds
SIMILARITY_THRESHOLD = 0.65       # embedding cosine similarity to flag as "same topic"
CONTRADICTION_DECAY = 0.4         # multiply old confidence by this when contradicted
CONTRADICTION_DECAY_MILD = 0.7    # milder decay when new fact is less confident
MIN_CONFIDENCE_FILTER = 0.2       # facts below this confidence are suppressed
MIN_NEW_FACT_CONFIDENCE = 0.3     # FC-003: ignore low-confidence new facts
CONFIDENCE_RATIO_MILD = 0.5       # FC-003: below this ratio apply mild decay instead of full
KEYWORD_OVERLAP_THRESHOLD = 0.5   # FC-005: Jaccard overlap for keyword fallback


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

        # Second pass: embedding-based semantic similarity check (FC-004 vectorised)
        if self._embed and self._embed.health_check():
            return self._detect_embedding_contradiction(new_fact, existing_facts)

        # Third pass: keyword-overlap fallback (FC-005) when embedding is unavailable
        return self._detect_keyword_contradiction(new_fact, existing_facts)

    def _detect_embedding_contradiction(
        self,
        new_fact: UserFact,
        existing_facts: list[UserFact],
    ) -> Optional[UserFact]:
        """FC-004 / FC-005: vectorised embedding similarity across all facts."""
        new_text = f"{new_fact.category} {new_fact.fact_key} {new_fact.fact_value}"
        try:
            new_vec = self._embed.encode([new_text])[0]
            old_texts = [
                f"{f.category} {f.fact_key} {f.fact_value}"
                for f in existing_facts
            ]
            old_vecs = self._embed.encode(old_texts)
            sims = self._cosine_sim_batch(new_vec, old_vecs)
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])
            best_match = existing_facts[best_idx]
            if (
                best_sim > SIMILARITY_THRESHOLD
                and best_match.fact_value.strip() != new_fact.fact_value.strip()
            ):
                logger.info(
                    f"[fact_check] semantic contradiction sim={best_sim:.2f}: "
                    f"'{best_match.fact_key}': '{best_match.fact_value}' vs '{new_fact.fact_value}'"
                )
                return best_match
            logger.debug(
                f"[fact_check] no semantic contradiction: best_sim={best_sim:.2f} "
                f"threshold={SIMILARITY_THRESHOLD}"
            )
        except Exception as e:
            logger.debug(f"[fact_check] embedding comparison failed: {e}")

        return None

    def _detect_keyword_contradiction(
        self,
        new_fact: UserFact,
        existing_facts: list[UserFact],
    ) -> Optional[UserFact]:
        """FC-005: keyword-overlap fallback when embedding engine is unavailable."""
        new_tokens = self._tokenize(
            f"{new_fact.category} {new_fact.fact_key} {new_fact.fact_value}"
        )
        if not new_tokens:
            return None

        best_match = None
        best_overlap = 0.0
        for f in existing_facts:
            old_tokens = self._tokenize(f"{f.category} {f.fact_key} {f.fact_value}")
            if not old_tokens:
                continue
            overlap = self._jaccard_overlap(new_tokens, old_tokens)
            if overlap > best_overlap and overlap >= KEYWORD_OVERLAP_THRESHOLD:
                if f.fact_value.strip() != new_fact.fact_value.strip():
                    best_overlap = overlap
                    best_match = f

        if best_match:
            logger.info(
                f"[fact_check] keyword contradiction overlap={best_overlap:.2f}: "
                f"'{best_match.fact_key}': '{best_match.fact_value}' vs '{new_fact.fact_value}'"
            )
        else:
            logger.debug(
                f"[fact_check] no keyword contradiction: best_overlap={best_overlap:.2f} "
                f"threshold={KEYWORD_OVERLAP_THRESHOLD}"
            )
        return best_match

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract normalised tokens for keyword overlap."""
        text = text.lower()
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text)
        return set(tokens)

    @staticmethod
    def _jaccard_overlap(a: set[str], b: set[str]) -> float:
        """Jaccard similarity between two token sets."""
        if not a or not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union else 0.0

    def resolve(
        self,
        new_fact: UserFact,
        old_fact: UserFact,
        ltm,  # #207: LongTermMemory, not repo — use sync wrappers
    ) -> bool:
        """FC-003: resolve contradiction with new-fact quality awareness.

        Returns True if the old fact was deactivated.
        """
        # FC-003: ignore low-quality new facts
        if new_fact.confidence < MIN_NEW_FACT_CONFIDENCE:
            logger.info(
                f"[fact_check] new fact confidence {new_fact.confidence:.2f} below "
                f"threshold {MIN_NEW_FACT_CONFIDENCE}; keeping old fact #{old_fact.id}"
            )
            return False

        # FC-003: confidence ratio determines resolution strength
        conf_ratio = new_fact.confidence / max(old_fact.confidence, 0.01)
        if conf_ratio < CONFIDENCE_RATIO_MILD:
            decay = CONTRADICTION_DECAY_MILD
        else:
            decay = CONTRADICTION_DECAY

        new_conf = old_fact.confidence * decay
        if new_conf < MIN_CONFIDENCE_FILTER:
            logger.warning(
                f"[fact_check] deactivating fact #{old_fact.id}: "
                f"'{old_fact.fact_key} = {old_fact.fact_value}' "
                f"contradicted by '{new_fact.fact_key} = {new_fact.fact_value}'"
            )
            ltm.deactivate_fact(old_fact.id)  # sync wrapper
            return True
        else:
            logger.info(
                f"[fact_check] decaying fact #{old_fact.id} confidence: "
                f"{old_fact.confidence:.2f} -> {new_conf:.2f} "
                f"(contradicted by '{new_fact.fact_key} = {new_fact.fact_value}')"
            )
            ltm.update_fact_confidence(old_fact.id, new_conf)  # sync wrapper
            return False

    def _cosine_sim_batch(
        self,
        new_vec: list[float],
        old_vecs: list[list[float]],
    ) -> np.ndarray:
        """FC-004: vectorised cosine similarity between one vector and many."""
        a = np.asarray(new_vec, dtype=float)
        b = np.asarray(old_vecs, dtype=float)
        if a.ndim == 1:
            a = a[np.newaxis, :]  # (1, d)
        # b shape: (n, d); a shape: (1, d)
        dots = np.dot(b, a.T).reshape(-1)  # (n,)
        norm_a = float(np.linalg.norm(a))
        norms_b = np.linalg.norm(b, axis=1)
        denom = norms_b * norm_a
        sims = np.divide(dots, denom, out=np.zeros(dots.shape, dtype=float), where=denom != 0)
        return sims

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        """FC-004: pairwise cosine similarity using numpy.

        Kept for compatibility with existing tests and small comparisons.
        """
        arr_a = np.asarray(a, dtype=float)
        arr_b = np.asarray(b, dtype=float)
        dot = float(np.dot(arr_a, arr_b))
        norm_a = float(np.linalg.norm(arr_a))
        norm_b = float(np.linalg.norm(arr_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
