"""Memory Agent — deterministic memory reasoning (layer1-memory P0+P1).

NOT an LLM agent: a deterministic pipeline that retrieves evidence with
vector recall, cross-verifies it, and reconstructs an answer with
confidence and an evidence chain. An optional LLM semantic-reconstruction
layer can sit on top of MemoryAnswer, but the core stays deterministic
and unit-testable. See doc/refactor/layer1-memory/memory-agent.md.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Optional

import numpy as np

from memory.embeddings import EmbeddingEngine
from memory.fact_checker import FactChecker
from memory.lifecycle import MemoryLifecycleManager
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from models.memory import EMBEDDING_VERSION, FactV2, UserFact

logger = logging.getLogger(__name__)


# ── Data models ──

@dataclass
class MemoryClues:
    """Structured clues from a query. Recall is vector-only; the only
    rule-based clue is time (vectors can't do time arithmetic)."""
    raw_query: str
    query_embedding: Optional[bytes] = None
    time_ranges: list[tuple[str, str]] = field(default_factory=list)  # absolute ISO dates
    intent: Optional[str] = None


@dataclass
class MemoryEvidence:
    """One piece of evidence with provenance."""
    source_type: Literal["observation", "fact", "experience", "relationship"]
    source_id: int
    content: str
    confidence: float
    timestamp: str
    verification_count: int = 1
    similarity: float = 0.0          # vector similarity to the query
    has_similarity: bool = False     # whether similarity was actually measurable
    is_contradicted: bool = False
    is_stale: bool = False


@dataclass
class MemoryAnswer:
    """Final output of the Memory Agent."""
    answer: str
    confidence: float
    evidences: list[MemoryEvidence] = field(default_factory=list)
    needs_more_evidence: bool = False
    contradictions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# ── Verification constants (memory-agent-verification.md) ──

SOURCE_QUALITY = {"fact": 1.0, "observation": 0.6, "experience": 0.5, "relationship": 0.3}
STABLE_CATEGORIES = {"preference", "identity", "relationship"}
CONSISTENCY_SIM_THRESHOLD = 0.7
WEIGHTS = {
    "consistency": 0.30, "verification": 0.20, "source_quality": 0.20,
    "freshness": 0.15, "timeline": 0.10, "contradiction": 0.05,
}

INTENT_ANCHORS = {
    "recall": ["还记得吗", "我们上次聊了什么", "之前发生过什么"],
    "verify": ["是不是这样", "你确定吗", "我说的对吗"],
    "compare": ["有什么区别", "哪个更好", "比较一下"],
    "summarize": ["总结一下", "讲讲这段时间", "概括一下"],
}
INTENT_THRESHOLD = 0.65

# Recall/summarize queries are topic-less ("上周我们聊了什么") — their query
# embedding carries no topic, so the relevance floor must not apply.
RECALL_LIKE_INTENTS = {"recall", "summarize"}


def parse_time_ranges(query: str, today: Optional[datetime] = None) -> list[tuple[str, str]]:
    """Parse Chinese relative time words into absolute (start, end) ISO dates.

    Resolved against the query day immediately, so ranges never drift
    across sessions. Natural week/month boundaries （一期统一按自然周期）.
    """
    now = today or datetime.now()
    d = now.date()
    ranges: list[tuple[str, str]] = []
    if re.search(r"前天", query):
        day = d - timedelta(days=2)
        ranges.append((day.isoformat(), day.isoformat()))
    if re.search(r"昨天", query):
        day = d - timedelta(days=1)
        ranges.append((day.isoformat(), day.isoformat()))
    if re.search(r"今天", query):
        ranges.append((d.isoformat(), d.isoformat()))
    if re.search(r"上周|上星期", query):
        monday = d - timedelta(days=d.weekday() + 7)
        ranges.append((monday.isoformat(), (monday + timedelta(days=6)).isoformat()))
    if re.search(r"这周|本周", query):
        monday = d - timedelta(days=d.weekday())
        ranges.append((monday.isoformat(), d.isoformat()))
    if re.search(r"上个月", query):
        end = d.replace(day=1) - timedelta(days=1)
        ranges.append((end.replace(day=1).isoformat(), end.isoformat()))
    if re.search(r"这个月|本月", query):
        ranges.append((d.replace(day=1).isoformat(), d.isoformat()))
    m = re.search(r"(\d{4})年(\d{1,2})月", query)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        start = datetime(year, month, 1).date()
        end = (datetime(year + (month == 12), month % 12 + 1, 1).date()
               - timedelta(days=1))
        ranges.append((start.isoformat(), end.isoformat()))
    m2 = re.search(r"(\d{1,2})月(\d{1,2})[日号]", query)
    if m2:
        try:
            day = datetime(d.year, int(m2.group(1)), int(m2.group(2))).date()
            ranges.append((day.isoformat(), day.isoformat()))
        except ValueError:
            pass
    return ranges


def check_timeline(evidences: list[MemoryEvidence], category: str = "event") -> float:
    """Timeline coherence, typed: long spans HURT event facts but mildly
    SUPPORT stable facts (preference/identity/relationship)."""
    dated = [e for e in evidences if e.timestamp]
    if len(dated) <= 1:
        return 1.0
    try:
        stamps = sorted(datetime.fromisoformat(e.timestamp) for e in dated)
    except ValueError:
        return 0.5
    days = (stamps[-1] - stamps[0]).days
    if category in STABLE_CATEGORIES:
        return min(0.8 + days / 365 * 0.2, 1.0)
    if days <= 1:
        return 1.0
    if days <= 7:
        return 0.8
    if days <= 30:
        return 0.6
    return 0.4


def check_freshness(evidences: list[MemoryEvidence],
                    now: Optional[datetime] = None) -> float:
    """How recent the newest evidence is."""
    dated = [e for e in evidences if e.timestamp]
    if not dated:
        return 0.0
    now = now or datetime.now()
    try:
        latest = max(datetime.fromisoformat(e.timestamp) for e in dated)
    except ValueError:
        return 0.5
    days_old = (now - latest).days
    if days_old <= 1:
        return 1.0
    if days_old <= 7:
        return 0.8
    if days_old <= 30:
        return 0.5
    if days_old <= 90:
        return 0.3
    return 0.1


class MemoryAgent:
    """记忆智能体：向量召回 → 交叉验证 → 带置信度的重构回答。"""

    FACTS_POOL = 50
    OBS_POOL = 50
    EXP_POOL = 30

    def __init__(self, ltm: LongTermMemory, lifecycle: MemoryLifecycleManager,
                 retriever: MemoryRetriever, embedding_engine=None,
                 fact_checker: Optional[FactChecker] = None,
                 relevance_floor: float = 0.35,
                 relevance_full: float = 0.75):
        self.ltm = ltm
        self.lifecycle = lifecycle
        self.retriever = retriever
        self._embed = embedding_engine
        self._fact_checker = fact_checker or FactChecker(embedding_engine=embedding_engine)
        self._intent_vecs: Optional[dict[str, np.ndarray]] = None  # lazy anchors
        # MA-002: relevance floor. Measurable evidences below relevance_floor
        # are dropped; final confidence is scaled by top_sim/relevance_full.
        self._relevance_floor = relevance_floor
        self._relevance_full = relevance_full

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
        verified, contradictions, consistency = await self._cross_verify(evidences)

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
        clues = MemoryClues(raw_query=query)
        clues.query_embedding = await self._encode_bytes(query)
        clues.time_ranges = parse_time_ranges(query)
        clues.intent = await self._classify_intent(clues.query_embedding)
        logger.debug(
            f"[memory_agent] clues: intent={clues.intent} "
            f"time_ranges={clues.time_ranges} "
            f"embed={'ok' if clues.query_embedding else 'none'}"
        )
        return clues

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
        """Returns (evidences, top_sim). top_sim is None when relevance was
        not applicable (no query vector, recall-like intent, or no measurable
        evidence); otherwise it is the max measured cosine similarity."""
        repo = self.ltm.repo
        qvec = None
        if clues.query_embedding is not None:
            try:
                qvec = EmbeddingEngine.bytes_to_vec(clues.query_embedding)
            except Exception:
                qvec = None

        # 禁止 asyncio.gather 并发 repo 查询：Database.cursor() 的
        # threading.Lock（H-03）跨 await 持有，同 loop 第二个协程的
        # 阻塞 acquire 会冻死整个事件循环（2026-07-20 生产死锁）。
        # SQLite 查询本身是毫秒级，串行没有性能损失。
        facts = await repo.get_active_facts_v2(limit=self.FACTS_POOL)
        observations = await repo.get_recent_observations(limit=self.OBS_POOL)
        experiences = await repo.get_recent_experiences(limit=self.EXP_POOL)
        relationship = await repo.get_all_relationships()

        def _measurable(blob, version) -> bool:
            return (qvec is not None and blob is not None
                    and version == EMBEDDING_VERSION)

        evidences: list[MemoryEvidence] = []
        for f in facts:
            evidences.append(MemoryEvidence(
                source_type="fact", source_id=f.id,
                content=f"{f.category}|{f.fact_key}: {f.fact_value}",
                confidence=f.confidence,
                timestamp=f.updated_at or f.created_at,
                verification_count=f.verification_count,
                similarity=self._sim(qvec, f.embedding, f.embedding_version),
                has_similarity=_measurable(f.embedding, f.embedding_version),
                is_contradicted=(f.status == "contradicted"),
                is_stale=(f.status not in ("active",)),
            ))
        for o in observations:
            evidences.append(MemoryEvidence(
                source_type="observation", source_id=o.id,
                content=o.content[:200],
                confidence=0.6, timestamp=o.created_at,
                similarity=self._sim(qvec, o.embedding, o.embedding_version),
                has_similarity=_measurable(o.embedding, o.embedding_version),
            ))
        for e in experiences:
            evidences.append(MemoryEvidence(
                source_type="experience", source_id=e.id,
                content=f"[{e.emotional_tone}] {e.summary}",
                confidence=e.composite_score, timestamp=e.created_at,
                similarity=self._sim(qvec, e.embedding, e.embedding_version),
                has_similarity=_measurable(e.embedding, e.embedding_version),
            ))
        if relationship:
            rel_text = "，".join(f"{k}={v:.2f}" for k, v in relationship.items())
            evidences.append(MemoryEvidence(
                source_type="relationship", source_id=0,
                content=f"关系指标：{rel_text}",
                confidence=0.3, timestamp=datetime.now().isoformat(),
            ))

        # Time post-filter (narrows by created date; recall itself is vector)
        if clues.time_ranges:
            before = len(evidences)
            evidences = [
                e for e in evidences
                if e.source_type == "relationship"
                or any(start <= e.timestamp[:10] <= end
                       for start, end in clues.time_ranges)
            ]
            logger.debug(f"[memory_agent] time filter: {before} -> {len(evidences)}")

        # MA-002 relevance floor: drop measurable evidences whose cosine
        # similarity to the query is below the floor. Unmeasurable evidences
        # (no/old embedding, relationship) are kept — relevance unknowable.
        # Skipped for recall-like intents: those queries carry no topic.
        top_sim: Optional[float] = None
        if qvec is not None and clues.intent not in RECALL_LIKE_INTENTS:
            meas_sims = [e.similarity for e in evidences if e.has_similarity]
            if meas_sims:
                top_sim = max(meas_sims)
                before = len(evidences)
                evidences = [
                    e for e in evidences
                    if not e.has_similarity
                    or e.similarity >= self._relevance_floor
                ]
                if len(evidences) != before:
                    logger.debug(
                        f"[memory_agent] relevance floor: {before} -> "
                        f"{len(evidences)} (floor={self._relevance_floor} "
                        f"top_sim={top_sim:.2f})"
                    )

        evidences.sort(key=lambda e: (e.similarity, e.confidence), reverse=True)
        kept = evidences[:max_evidence]
        kept_sim = f"{kept[0].similarity:.2f}" if kept else "-"
        logger.debug(
            f"[memory_agent] retrieve: facts={len(facts)} obs={len(observations)} "
            f"exp={len(experiences)} rel={bool(relationship)} "
            f"kept={len(kept)} top_sim={kept_sim}"
        )
        return kept, top_sim

    @staticmethod
    def _sim(qvec: Optional[np.ndarray], blob, version: int) -> float:
        if qvec is None or blob is None or version != EMBEDDING_VERSION:
            return 0.0
        try:
            vec = EmbeddingEngine.bytes_to_vec(bytes(blob), dim=len(qvec))
            return float(np.dot(vec, qvec))
        except Exception:
            return 0.0

    # ── Cross verification ──

    async def _cross_verify(self, evidences: list[MemoryEvidence],
                            ) -> tuple[list[MemoryEvidence], list[str], float]:
        contradictions = self._detect_contradictions(evidences)
        consistency = await self._check_consistency(evidences)
        return evidences, contradictions, consistency

    def _detect_contradictions(self, evidences: list[MemoryEvidence]) -> list[str]:
        """Direct fact-level conflicts: same category|key with a different
        value. Free-text observations are not contradiction-checked."""
        contradictions: list[str] = []
        by_key: dict[str, MemoryEvidence] = {}
        for e in evidences:
            if e.source_type != "fact":
                continue
            key = e.content.split(":", 1)[0]
            prev = by_key.get(key)
            if prev is not None and prev.content != e.content:
                contradictions.append(f"{prev.content[:50]} vs {e.content[:50]}")
                prev.is_contradicted = True
                e.is_contradicted = True
            else:
                by_key[key] = e
        return contradictions

    async def _check_consistency(self, evidences: list[MemoryEvidence]) -> float:
        """Mean pairwise cosine similarity of evidence contents, clipped to
        [0, 1]. One batch encode; without an embed engine the score is
        neutral. Similar → ~1.0; orthogonal topics → ~0.0."""
        if len(evidences) <= 1:
            return 1.0
        if not self._embed:
            return 0.5
        try:
            texts = [e.content for e in evidences]
            loop = asyncio.get_running_loop()
            vecs = await loop.run_in_executor(None, self._embed.encode, texts)
            sims = np.dot(vecs, vecs.T)
            iu = np.triu_indices(len(evidences), k=1)
            return float(np.clip(sims[iu].mean(), 0.0, 1.0))
        except Exception as e:
            logger.debug(f"[memory_agent] consistency check failed: {e}")
            return 0.5

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
