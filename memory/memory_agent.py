"""Memory Agent — deterministic memory reasoning (layer1-memory P0+P1).

NOT an LLM agent: a deterministic pipeline that retrieves evidence with
vector recall, cross-verifies it, and reconstructs an answer with
confidence and an evidence chain. An optional LLM semantic-reconstruction
layer can sit on top of MemoryAnswer, but the core stays deterministic
and unit-testable. See doc/refactor/layer1-memory/memory-agent.md.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from memory.embeddings import EmbeddingEngine
from memory.fact_checker import FactChecker
from memory.lifecycle import MemoryLifecycleManager
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.retrieval_pipeline import (
    FACTS_POOL, OBS_POOL, EXP_POOL, INSIGHT_POOL,
    SOURCE_QUALITY, STABLE_CATEGORIES, CONSISTENCY_SIM_THRESHOLD, WEIGHTS,
    RECALL_LIKE_INTENTS,
    QueryClues, MemoryEvidence,
    parse_time_ranges, check_timeline, check_freshness,
    retrieve_bundle, cross_verify,
)
from models.memory import EMBEDDING_VERSION, FactV2, UserFact
from prompts.templates import COREFERENCE_REWRITE_PROMPT, safe_format

logger = logging.getLogger(__name__)


# Backward-compatible alias: MemoryClues was renamed QueryClues in Layer 3.
MemoryClues = QueryClues


@dataclass
class MemoryAnswer:
    """Final output of the Memory Agent."""
    answer: str
    confidence: float
    evidences: list[MemoryEvidence] = field(default_factory=list)
    needs_more_evidence: bool = False
    contradictions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


INTENT_ANCHORS = {
    "recall": ["还记得吗", "我们上次聊了什么", "之前发生过什么"],
    "verify": ["是不是这样", "你确定吗", "我说的对吗"],
    "compare": ["有什么区别", "哪个更好", "比较一下"],
    "summarize": ["总结一下", "讲讲这段时间", "概括一下"],
}
INTENT_THRESHOLD = 0.65

# P2: 指代性问句的向量锚点（《国际歌》案例：「本地有这个歌吗」→「本地有《国际歌》吗」）。
# 与 INTENT_ANCHORS 同机制：query 向量与锚点的最大余弦 ≥ 阈值 → 触发 LLM 改写，
# 不做关键字匹配（# 指代检测与意图分类同一哲学：语义问题用向量，不用正则）。
# R2: 锚点收紧为 4 个强指代句，阈值 0.65→0.78（原太松，短句也命中）。
COREFERENCE_ANCHORS = [
    "这个是什么意思", "那首歌叫什么", "它在哪里",
    "上面说的那个",
]
COREFERENCE_THRESHOLD = 0.78


class MemoryAgent:
    """记忆智能体：向量召回 → 交叉验证 → 带置信度的重构回答。"""

    FACTS_POOL = FACTS_POOL
    OBS_POOL = OBS_POOL
    EXP_POOL = EXP_POOL
    INSIGHT_POOL = INSIGHT_POOL

    def __init__(self, ltm: LongTermMemory, lifecycle: MemoryLifecycleManager,
                 retriever: MemoryRetriever, embedding_engine=None,
                 fact_checker: Optional[FactChecker] = None,
                 relevance_floor: float = 0.35,
                 relevance_full: float = 0.75,
                 coreference_threshold: float = 0.78,  # R2
                 llm_fn=None, history_fn=None,
                 inner_drive_state=None):
        self.ltm = ltm
        self.lifecycle = lifecycle
        self.retriever = retriever
        self._embed = embedding_engine
        self._fact_checker = fact_checker or FactChecker(embedding_engine=embedding_engine)
        self._inner_drive_state = inner_drive_state  # L4-6b: optional curiosity sink
        self._intent_vecs: Optional[dict[str, np.ndarray]] = None  # lazy anchors
        # MA-002: relevance floor. Measurable evidences below relevance_floor
        # are dropped; final confidence is scaled by top_sim/relevance_full.
        self._relevance_floor = relevance_floor
        self._relevance_full = relevance_full
        self._coreference_threshold = coreference_threshold  # R2: 指代改写阈值
        # P2: LLM 版线索提取——llm_fn(prompt)->str 用于指代解析，
        # history_fn()->str 提供最近对话。两者缺一则回退纯规则路径。
        self._llm_fn = llm_fn
        self._history_fn = history_fn
        self._coref_vecs: Optional[np.ndarray] = None  # lazy 指代锚点

    # ── Public API ──

    async def answer(self, query: str, max_evidence: int = 10) -> MemoryAnswer:
        """Answer a question about the past with evidence + confidence."""
        clues = await self._extract_clues(query)
        evidences, top_sim = await self._retrieve_parallel(clues, max_evidence)
        verified, contradictions, consistency = await self._cross_verify(evidences)
        result = self._reconstruct(query, verified, contradictions, consistency,
                                   top_sim=top_sim)
        sim_log = f"{top_sim:.2f}" if top_sim is not None else "n/a"
        logger.info(
            f"[memory_agent] answer: query={query[:40]!r} "
            f"evidences={len(result.evidences)} confidence={result.confidence} "
            f"top_sim={sim_log} contradictions={len(result.contradictions)}"
        )
        return result

    async def verify_fact(self, fact_id: int) -> MemoryAnswer:
        """Proactively verify whether a FactV2 still holds."""
        repo = self.ltm.repo
        fact = await repo.get_fact_v2_by_id(fact_id)
        if not fact:
            return MemoryAnswer(answer="找不到该事实", confidence=0.0,
                                needs_more_evidence=True)
        clues = await self._extract_clues(f"{fact.fact_key} {fact.fact_value}")
        evidences, top_sim = await self._retrieve_parallel(clues, max_evidence=10)
        verified, contradictions, consistency = await self._cross_verify(
            evidences, self._embed)

        # FactChecker semantic contradiction against sibling facts
        candidates = await repo.search_facts_v2(fact.fact_key, limit=5)
        others = [c for c in candidates if c.id != fact.id]
        if others:
            conflict = self._fact_checker.detect_contradiction(
                UserFact(category=fact.category, fact_key=fact.fact_key,
                         fact_value=fact.fact_value),
                [UserFact(category=c.category, fact_key=c.fact_key,
                          fact_value=c.fact_value) for c in others],
            )
            if conflict:
                contradictions.append(
                    f"{fact.fact_key}: '{fact.fact_value}' vs '{conflict.fact_value}'")

        # L4-6b: contradiction becomes a curiosity entry in the inner drive.
        if contradictions and self._inner_drive_state is not None:
            try:
                content = (
                    f"「{fact.fact_key}」的记忆存在矛盾：{contradictions[0]}，"
                    f"找机会确认"
                )
                self._inner_drive_state.apply_updates(
                    add=[{"type": "curiosity", "content": content, "priority": 0.6}],
                    source="memory_agent",
                )
                logger.info(f"[memory_agent] curiosity created from contradiction: "
                            f"{fact.fact_key}")
            except Exception as e:
                logger.debug(f"[memory_agent] failed to write curiosity: {e}")

        result = self._reconstruct_fact_verification(
            fact, verified, contradictions, consistency, top_sim=top_sim)
        logger.info(
            f"[memory_agent] verify_fact: id={fact_id} "
            f"confidence={result.confidence} verdict={result.answer[:40]}"
        )
        return result

    async def correct_fact(self, old_fact_id: int, new_value: str,
                           source_turn: int) -> FactV2:
        """User correction: archive the correction as an Observation, mark the
        old Fact contradicted, promote the new value as a fresh Fact."""
        old_fact = await self.ltm.repo.get_fact_v2_by_id(old_fact_id)
        old_value = old_fact.fact_value if old_fact else "unknown"
        logger.info(f"[memory_agent] correct_fact: id={old_fact_id} '{old_value}' → '{new_value}'")
        obs = await self.lifecycle.observe(
            content=f"用户纠正：{old_value} → {new_value}",
            source_turn=source_turn,
            created_by="user_correction",
        )
        await self.lifecycle.contradict_fact(old_fact_id, reason="user correction")
        return await self.lifecycle.promote_fact(
            observation_ids=[obs.id],
            category=old_fact.category if old_fact else "preference",
            key=old_fact.fact_key if old_fact else "unknown",
            value=new_value,
            confidence=1.0, stability=0.8, freshness=1.0, importance=0.9,
            created_by="user_correction",
        )

    async def batch_verify_facts(self, limit: int = 10,
                                 decay_threshold: float = 0.3,
                                 decay_factor: float = 0.5) -> list[MemoryAnswer]:
        """Minimal sleep-consolidation (P1): re-verify the least-recently
        verified facts and decay those that no longer hold."""
        repo = self.ltm.repo
        facts = await repo.get_active_facts_v2(limit=200)
        facts.sort(key=lambda f: f.last_verified_at or "")
        answers = []
        for fact in facts[:limit]:
            result = await self.verify_fact(fact.id)
            answers.append(result)
            if result.confidence < decay_threshold:
                logger.info(f"[memory_agent] decay low-confidence fact "
                            f"id={fact.id} confidence={result.confidence}")
                await repo.decay_fact_v2(fact.id, decay_factor)
        return answers

    # ── Clue extraction (P1: time ranges + intent anchors) ──

    async def _extract_clues(self, query: str) -> MemoryClues:
        qvec_blob = await self._encode_bytes(query)
        resolved = query
        if await self._needs_coreference(qvec_blob):
            resolved = await self._rewrite_query(query)
            if resolved != query:
                qvec_blob = await self._encode_bytes(resolved)
        clues = MemoryClues(raw_query=resolved)
        clues.query_embedding = qvec_blob
        clues.time_ranges = parse_time_ranges(resolved)
        clues.intent = await self._classify_intent(clues.query_embedding)
        logger.debug(
            f"[memory_agent] clues: intent={clues.intent} "
            f"time_ranges={clues.time_ranges} "
            f"embed={'ok' if clues.query_embedding else 'none'}"
        )
        return clues

    async def _needs_coreference(self, query_blob: Optional[bytes]) -> bool:
        """P2: 指代性问句检测——向量锚点，不用关键字。锚点语义是「依赖上文
        才能理解的问句」（这个/那首/它/后来呢），与 query 求最大余弦。"""
        if not self._llm_fn or not self._history_fn:
            return False
        if not self._embed or query_blob is None:
            return False
        try:
            if self._coref_vecs is None:
                loop = asyncio.get_running_loop()
                self._coref_vecs = await loop.run_in_executor(
                    None, self._embed.encode, COREFERENCE_ANCHORS)
            qvec = EmbeddingEngine.bytes_to_vec(query_blob)
            sim = float(np.max(np.dot(self._coref_vecs, qvec)))
            logger.debug(f"[memory_agent] coreference anchor sim={sim:.2f} threshold={self._coreference_threshold:.2f}")
            return sim >= self._coreference_threshold
        except Exception as e:
            logger.debug(f"[memory_agent] coreference anchor check failed: {e}")
            return False

    async def _rewrite_query(self, query: str) -> str:
        """结合最近对话用 LLM 把指代性 query 改写为自足查询。
        历史为空、LLM 失败或输出异常（空/复读超长）一律回退原 query。"""
        try:
            history = self._history_fn() or ""
            if not history.strip():
                return query
            prompt = safe_format(COREFERENCE_REWRITE_PROMPT,
                                 history=history, query=query)
            loop = asyncio.get_running_loop()
            rewritten = await loop.run_in_executor(None, self._llm_fn, prompt)
            # 只取第一行、去引号；过长（失控复读）则弃用
            rewritten = (rewritten or "").strip().strip('"').split("\n")[0].strip()
            if not rewritten or len(rewritten) > max(len(query) * 4, 50):
                return query
            if rewritten != query:
                logger.info(f"[memory_agent] coreference: {query[:30]!r} "
                            f"-> {rewritten[:50]!r}")
            else:
                # R2: 空转统计——改写结果与原句相同只记 debug
                logger.debug(f"[memory_agent] coreference rewrite no-op: {query[:30]!r}")
            return rewritten
        except Exception as e:
            logger.warning(f"[memory_agent] coreference resolve failed: {e}")
            return query

    async def _encode_bytes(self, text: str) -> Optional[bytes]:
        if not self._embed or not text.strip():
            return None
        try:
            loop = asyncio.get_running_loop()
            vec = await loop.run_in_executor(None, self._embed.encode_single, text)
            return EmbeddingEngine.vec_to_bytes(vec)
        except Exception as e:
            logger.debug(f"[memory_agent] encode failed: {e}")
            return None

    async def _classify_intent(self, query_blob: Optional[bytes]) -> Optional[str]:
        """Intent via vector anchors (no regex). Below threshold → None."""
        if not self._embed or query_blob is None:
            return None
        try:
            if self._intent_vecs is None:
                anchors = [a for group in INTENT_ANCHORS.values() for a in group]
                loop = asyncio.get_running_loop()
                vecs = await loop.run_in_executor(None, self._embed.encode, anchors)
                self._intent_vecs = {}
                i = 0
                for intent, group in INTENT_ANCHORS.items():
                    self._intent_vecs[intent] = vecs[i:i + len(group)]
                    i += len(group)
            qvec = EmbeddingEngine.bytes_to_vec(query_blob)
            best_intent, best_sim = None, 0.0
            for intent, group_vecs in self._intent_vecs.items():
                sim = float(np.max(np.dot(group_vecs, qvec)))
                if sim > best_sim:
                    best_intent, best_sim = intent, sim
            return best_intent if best_sim >= INTENT_THRESHOLD else None
        except Exception as e:
            logger.debug(f"[memory_agent] intent classification failed: {e}")
            return None

    # ── Parallel retrieval (vector recall, no keyword filtering) ──

    async def _retrieve_parallel(self, clues: MemoryClues,
                                 max_evidence: int,
                                 ) -> tuple[list[MemoryEvidence], Optional[float]]:
        """Thin wrapper around retrieval_pipeline.retrieve_bundle.
        Retrieval is kept serial because Database.cursor() holds a process-wide
        threading.Lock (H-03); concurrent acquires in the same loop would
        deadlock the event loop.
        """
        return await retrieve_bundle(
            self.ltm.repo, clues, max_evidence, self._relevance_floor
        )

    # ── Cross verification ──

    async def _cross_verify(self, evidences: list[MemoryEvidence],
                            embed=None,
                            ) -> tuple[list[MemoryEvidence], list[str], float]:
        """Thin wrapper around retrieval_pipeline.cross_verify.

        ``embed`` defaults to ``self._embed`` so consistency checks do not
        silently fall back to the neutral 0.5 score.
        """
        return await cross_verify(evidences, embed or self._embed)

    # ── Confidence + reconstruction ──

    def _compute_confidence(self, evidences: list[MemoryEvidence],
                            contradictions: list[str], consistency: float,
                            category: str = "event",
                            top_sim: Optional[float] = None) -> float:
        if not evidences:
            return 0.0
        timeline = check_timeline(evidences, category=category)
        freshness = check_freshness(evidences)
        avg_source = sum(SOURCE_QUALITY.get(e.source_type, 0.3) for e in evidences) / len(evidences)
        avg_verif = sum(e.verification_count for e in evidences) / len(evidences)
        verification_score = min(avg_verif / 3.0, 1.0)
        penalty = 1.0 - min(len(contradictions) * 0.2, 0.5)
        score = (
            consistency * WEIGHTS["consistency"]
            + verification_score * WEIGHTS["verification"]
            + avg_source * WEIGHTS["source_quality"]
            + freshness * WEIGHTS["freshness"]
            + timeline * WEIGHTS["timeline"]
            + penalty * WEIGHTS["contradiction"]
        )
        # MA-002: scale by query relevance so off-topic recall (e.g. "你好"
        # pulling 10 noise evidences) cannot reach a high confidence.
        if top_sim is not None:
            score *= min(top_sim / self._relevance_full, 1.0)
        return round(score, 2)

    def _reconstruct(self, query: str, evidences: list[MemoryEvidence],
                     contradictions: list[str], consistency: float,
                     top_sim: Optional[float] = None) -> MemoryAnswer:
        if not evidences:
            return MemoryAnswer(
                answer="没有找到相关记忆。", confidence=0.0,
                needs_more_evidence=True,
                suggestions=["换个说法问问，或先和我聊聊这个话题"],
            )
        category = self._dominant_category(evidences)
        confidence = self._compute_confidence(evidences, contradictions,
                                              consistency, category=category,
                                              top_sim=top_sim)
        parts = []
        top_facts = [e for e in evidences if e.source_type == "fact"][:2]
        others = [e for e in evidences if e.source_type != "fact"][:2]
        for e in top_facts:
            suffix = "（存在矛盾）" if e.is_contradicted else ""
            parts.append(f"{e.content}{suffix}")
        for e in others:
            parts.append(f"相关记忆：{e.content[:100]}")
        suggestions = []
        if contradictions:
            suggestions.append("存在矛盾的记忆，需要用户确认")
        needs_more = confidence < 0.4
        if needs_more:
            suggestions.append("证据不足，建议继续观察")
        return MemoryAnswer(
            answer="\n".join(parts), confidence=confidence, evidences=evidences,
            needs_more_evidence=needs_more, contradictions=contradictions,
            suggestions=suggestions,
        )

    def _reconstruct_fact_verification(self, fact: FactV2,
                                       evidences: list[MemoryEvidence],
                                       contradictions: list[str],
                                       consistency: float,
                                       top_sim: Optional[float] = None) -> MemoryAnswer:
        confidence = self._compute_confidence(evidences, contradictions,
                                              consistency, category=fact.category,
                                              top_sim=top_sim)
        label = f"「{fact.fact_key}: {fact.fact_value}」"
        if contradictions:
            verdict = f"事实{label}存在矛盾证据"
        elif confidence >= 0.6:
            verdict = f"事实{label}仍然成立"
        elif confidence >= 0.3:
            verdict = f"事实{label}缺乏近期证据支持"
        else:
            verdict = f"事实{label}可能已过时"
        suggestions = []
        if confidence < 0.3:
            suggestions.append("建议 decay 或向用户确认")
        return MemoryAnswer(
            answer=verdict, confidence=confidence, evidences=evidences,
            needs_more_evidence=confidence < 0.4,
            contradictions=contradictions, suggestions=suggestions,
        )

    @staticmethod
    def _dominant_category(evidences: list[MemoryEvidence]) -> str:
        for e in evidences:
            if e.source_type == "fact":
                return e.content.split("|", 1)[0]
        return "event"
