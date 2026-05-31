import logging
import re
from typing import Optional

import numpy as np

from models.conversation import MemoryContext
from models.memory import UserFact
from memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Three-layer memory retrieval:
    Layer 1: Hot Memory -- always included (high-score facts, recent experiences)
    Layer 2: Hybrid Search -- semantic (0.6) + keyword (0.4) with optional LLM rerank
    Layer 3: On-demand -- triggered by "[回忆: xxx]" syntax
    """

    def __init__(self, long_term: LongTermMemory, llm_rerank_fn: Optional[callable] = None,
                 embedding_engine=None):
        self.ltm = long_term
        self.llm_rerank_fn = llm_rerank_fn
        self._embed = embedding_engine

    def retrieve_for_query(self, query: str) -> MemoryContext:
        """Layer 1 + Layer 2: build context for a user message."""
        logger.info(f"[retrieval] query_len={len(query)}")

        # Layer 1: hot memory (always included)
        hot_facts = self.ltm.get_all_active_facts(limit=50)
        recent_experiences = self.ltm.get_recent_experiences(limit=5)
        reflections = self.ltm.get_recent_reflections(limit=3)
        relationship = self.ltm.get_relationship()

        # Layer 2: hybrid or keyword scoring
        keywords = self._extract_keywords(query)
        if self._embed and self._embed.health_check():
            candidates = self._hybrid_score(query, hot_facts, keywords)
        else:
            candidates = self._score_facts(hot_facts, keywords, query)
        candidates = candidates[:30]

        # LLM reranking if > 15 candidates
        if len(candidates) > 15 and self.llm_rerank_fn and query.strip():
            selected_indices = self._llm_rerank(query, candidates)
            if selected_indices is not None:
                candidates = [candidates[i] for i in selected_indices if i < len(candidates)]

        selected_facts = candidates[:10]

        # Search experiences (semantic if available)
        if self._embed and self._embed.health_check():
            keyword_experiences = self._search_experiences_semantic(
                query, recent_experiences, keywords
            )
        else:
            keyword_experiences = self.ltm.search_experiences(keywords, limit=5)
        all_experiences = self._merge_unique_experiences(
            keyword_experiences, recent_experiences
        )[:5]

        return MemoryContext(
            facts=selected_facts,
            experiences=all_experiences,
            reflections=reflections[:3],
            relationship=relationship,
        )

    def retrieve_by_recall_tag(self, text: str) -> Optional[str]:
        """Layer 3: check for [回忆: xxx] tag and return memory snippet."""
        m = re.search(r'\[回忆:\s*(.+?)\]', text)
        if not m:
            return None
        query = m.group(1).strip()
        keywords = self._extract_keywords(query)
        facts = self.ltm.search_facts(query, limit=5)
        experiences = self.ltm.search_experiences(keywords, limit=3)
        reflections = self.ltm.get_recent_reflections(limit=2)

        parts = []
        if facts:
            parts.append("关于用户：")
            for f in facts:
                parts.append(f"- {f.fact_key}: {f.fact_value}")
        if experiences:
            parts.append("相关回忆：")
            for e in experiences:
                parts.append(f"- [{e.emotional_tone}] {e.summary}")
        if reflections:
            parts.append("相关反思：")
            for r in reflections:
                parts.append(f"- {r.content}")
        return "\n".join(parts) if parts else None

    def check_recall_tag(self, response_text: str) -> Optional[str]:
        """Check if AI response contains [回忆:] and return query."""
        m = re.search(r'\[回忆:\s*(.+?)\]', response_text)
        if m:
            return m.group(1).strip()
        return None

    # ── Hybrid scoring ──

    def _hybrid_score(self, query: str, candidates: list, keywords: list) -> list:
        """Hybrid scoring: semantic (0.6) + keyword (0.4)."""
        SEMANTIC_WEIGHT = 0.6
        KEYWORD_WEIGHT = 0.4

        try:
            query_vec = self._embed.encode_single(query)
        except Exception as e:
            logger.warning(f"[retrieval] embed failed, fallback to keyword: {e}")
            return self._score_facts(candidates, keywords, query)

        from memory.embeddings import EmbeddingEngine

        scores = []
        for c in candidates:
            semantic = 0.0
            if hasattr(c, 'embedding') and c.embedding is not None:
                try:
                    vec = EmbeddingEngine.bytes_to_vec(bytes(c.embedding))
                    semantic = float(np.dot(vec, query_vec))
                except Exception:
                    pass

            keyword = self._keyword_score_single(c, keywords, query)
            final = semantic * SEMANTIC_WEIGHT + keyword * KEYWORD_WEIGHT
            scores.append((c, final))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scores[:30]]

    def _search_experiences_semantic(self, query: str, recent: list,
                                     keywords: list) -> list:
        """Semantic + keyword hybrid experience search."""
        all_exp = self.ltm.search_experiences(keywords, limit=15)
        combined = self._merge_unique_experiences(all_exp, recent)
        if not combined or not self._embed:
            return all_exp

        try:
            query_vec = self._embed.encode_single(query)
        except Exception:
            return all_exp

        from memory.embeddings import EmbeddingEngine
        scored = []
        for exp in combined:
            sim = 0.0
            if hasattr(exp, 'embedding') and exp.embedding is not None:
                try:
                    vec = EmbeddingEngine.bytes_to_vec(bytes(exp.embedding))
                    sim = float(np.dot(vec, query_vec))
                except Exception:
                    pass
            scored.append((exp, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [exp for exp, _ in scored[:5]]

    # ── Keyword scoring (existing, extracted for reuse) ──

    @staticmethod
    def _keyword_score_single(f: UserFact, keywords: list[str], query: str) -> float:
        """Score a single fact by keyword match."""
        score = f.composite_score * 0.2
        score += f.importance * 0.3
        keyword_hits = sum(1 for kw in keywords
                           if kw in f.fact_key.lower()
                           or kw in f.fact_value.lower()
                           or kw in f.category.lower())
        score += keyword_hits * 0.2
        if any(kw == f.category for kw in keywords):
            score += 0.2
        score -= min(f.recall_count * 0.02, 0.3)
        return max(0, score)

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        words = re.findall(r'[\w一-鿿]+', text.lower())
        stopwords = {
            "的", "了", "在", "是", "我", "你", "他", "她", "它",
            "有", "和", "就", "也", "这", "那", "不", "吗", "吧",
            "啊", "呢", "哦", "嗯", "哈", "呀", "嘛",
            "a", "an", "the", "is", "are", "was", "were",
            "i", "you", "he", "she", "it", "we", "they",
            "do", "does", "did", "have", "has", "had",
        }
        return [w for w in words if w not in stopwords and len(w) > 1]

    @staticmethod
    def _score_facts(facts: list[UserFact], keywords: list[str],
                     query: str) -> list[UserFact]:
        """Pure keyword scoring (fallback when embedding is unavailable)."""
        scored = []
        for f in facts:
            f.composite_score = MemoryRetriever._keyword_score_single(f, keywords, query)
            scored.append(f)
        scored.sort(key=lambda x: x.composite_score, reverse=True)
        return scored

    def _llm_rerank(self, query: str, candidates: list[UserFact],
                    max_candidates: int = 15) -> Optional[list[int]]:
        from prompts.templates import MEMORY_RERANK_PROMPT

        candidate_lines = []
        for i, f in enumerate(candidates[:30]):
            candidate_lines.append(f"{i}. [{f.category}] {f.fact_key}: {f.fact_value}")

        prompt = MEMORY_RERANK_PROMPT.format(
            query=query,
            candidates="\n".join(candidate_lines),
        )

        try:
            result = self.llm_rerank_fn(prompt)
            if not result or result.strip().upper() == "NONE":
                return None
            indices = [int(x.strip()) for x in result.split(",") if x.strip().isdigit()]
            return indices[:max_candidates]
        except Exception as e:
            logger.warning(f"LLM rerank failed: {e}")
            return None

    @staticmethod
    def _merge_unique_experiences(*lists: list) -> list:
        seen = set()
        result = []
        for lst in lists:
            for e in lst:
                if e.id not in seen:
                    seen.add(e.id)
                    result.append(e)
        return result
