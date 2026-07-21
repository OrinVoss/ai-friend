"""Layer 3 multi-stage retrieval pipeline.

Separates the shared memory retrieval/cross-verification flow from the
MemoryAgent orchestration so that the same evidence bundle can be rendered
into different context profiles for different consumers (Agent 1 full text,
Agent 3 light context, etc.).
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Optional

import numpy as np

from memory.embeddings import EmbeddingEngine
from models.memory import EMBEDDING_VERSION

logger = logging.getLogger(__name__)


# ── Data models ──

@dataclass
class QueryClues:
    """Structured clues from a query. Recall is vector-only; the only
    rule-based clue is time (vectors can't do time arithmetic)."""
    raw_query: str
    query_embedding: Optional[bytes] = None
    time_ranges: list[tuple[str, str]] = field(default_factory=list)  # absolute ISO dates
    intent: Optional[str] = None


@dataclass
class MemoryEvidence:
    """One piece of evidence with provenance."""
    source_type: Literal["observation", "fact", "experience", "relationship", "insight"]
    source_id: int
    content: str
    confidence: float
    timestamp: str
    verification_count: int = 1
    similarity: float = 0.0          # vector similarity to the query
    has_similarity: bool = False     # whether similarity was actually measurable
    is_contradicted: bool = False
    is_stale: bool = False


# ── Retrieval constants ──

SOURCE_QUALITY = {"fact": 1.0, "insight": 0.6, "observation": 0.6,
                  "experience": 0.5, "relationship": 0.3}
STABLE_CATEGORIES = {"preference", "identity", "relationship"}
CONSISTENCY_SIM_THRESHOLD = 0.7
WEIGHTS = {
    "consistency": 0.30, "verification": 0.20, "source_quality": 0.20,
    "freshness": 0.15, "timeline": 0.10, "contradiction": 0.05,
}

# Recall/summarize queries are topic-less ("上周我们聊了什么") — their query
# embedding carries no topic, so the relevance floor must not apply.
RECALL_LIKE_INTENTS = {"recall", "summarize"}

FACTS_POOL = 50
OBS_POOL = 50
EXP_POOL = 30
INSIGHT_POOL = 20


# ── Time / freshness / timeline helpers ──

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


# ── Vector similarity helper ──

def _sim(qvec: Optional[np.ndarray], blob, version: int) -> float:
    if qvec is None or blob is None or version != EMBEDDING_VERSION:
        return 0.0
    try:
        vec = EmbeddingEngine.bytes_to_vec(bytes(blob), dim=len(qvec))
        return float(np.dot(vec, qvec))
    except Exception:
        return 0.0


# ── Retrieval bundle ──

async def retrieve_bundle(
    repo, clues: QueryClues, max_evidence: int,
    relevance_floor: float, recall_like_intents: set = RECALL_LIKE_INTENTS,
) -> tuple[list[MemoryEvidence], Optional[float]]:
    """五源串行召回 + 时间后过滤 + 相关性下限 + 排序截断。

    Returns (evidences, top_sim). top_sim is None when relevance was not
    applicable (no query vector, recall-like intent, or no measurable evidence);
    otherwise it is the max measured cosine similarity.

    禁止 asyncio.gather 并发 repo 查询：storage/database.py::cursor() 持有
    进程级 threading.Lock（H-03），同 loop 并发 acquire 会冻死事件循环
    （2026-07-20 生产死锁）。SQLite 查询毫秒级，串行无损失。
    """
    qvec = None
    if clues.query_embedding is not None:
        try:
            qvec = EmbeddingEngine.bytes_to_vec(clues.query_embedding)
        except Exception:
            qvec = None

    facts = await repo.get_active_facts_v2(limit=FACTS_POOL)
    observations = await repo.get_recent_observations(limit=OBS_POOL)
    experiences = await repo.get_recent_experiences(limit=EXP_POOL)
    relationship = await repo.get_all_relationships()
    insights = await repo.get_active_insights(limit=INSIGHT_POOL)

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
            similarity=_sim(qvec, f.embedding, f.embedding_version),
            has_similarity=_measurable(f.embedding, f.embedding_version),
            is_contradicted=(f.status == "contradicted"),
            is_stale=(f.status not in ("active",)),
        ))
    for o in observations:
        evidences.append(MemoryEvidence(
            source_type="observation", source_id=o.id,
            content=o.content[:200],
            confidence=0.6, timestamp=o.created_at,
            similarity=_sim(qvec, o.embedding, o.embedding_version),
            has_similarity=_measurable(o.embedding, o.embedding_version),
        ))
    for e in experiences:
        dream_prefix = "【梦境，非真实事件】" if ("dream" in (e.tags or [])) else ""
        evidences.append(MemoryEvidence(
            source_type="experience", source_id=e.id,
            content=f"{dream_prefix}[{e.emotional_tone}] {e.summary}",
            confidence=e.composite_score, timestamp=e.created_at,
            similarity=_sim(qvec, e.embedding, e.embedding_version),
            has_similarity=_measurable(e.embedding, e.embedding_version),
        ))
    for i in insights:
        suspect = "（待验证）" if i.needs_more_evidence else ""
        evidences.append(MemoryEvidence(
            source_type="insight", source_id=i.id,
            content=f"洞察[{i.insight_type or 'general'}]{suspect}：{i.hypothesis}",
            confidence=i.confidence,
            timestamp=i.updated_at or i.created_at,
            verification_count=0 if i.needs_more_evidence else 1,
            similarity=_sim(qvec, i.embedding, i.embedding_version),
            has_similarity=_measurable(i.embedding, i.embedding_version),
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
        logger.debug(f"[retrieval_pipeline] time filter: {before} -> {len(evidences)}")

    # MA-002 relevance floor: drop measurable evidences whose cosine similarity
    # to the query is below the floor. Unmeasurable evidences (no/old embedding,
    # relationship) are kept — relevance unknowable. Skipped for recall-like
    # intents: those queries carry no topic.
    top_sim: Optional[float] = None
    if qvec is not None and clues.intent not in recall_like_intents:
        meas_sims = [e.similarity for e in evidences if e.has_similarity]
        if meas_sims:
            top_sim = max(meas_sims)
            before = len(evidences)
            evidences = [
                e for e in evidences
                if not e.has_similarity
                or e.similarity >= relevance_floor
            ]
            if len(evidences) != before:
                logger.debug(
                    f"[retrieval_pipeline] relevance floor: {before} -> "
                    f"{len(evidences)} (floor={relevance_floor} "
                    f"top_sim={top_sim:.2f})"
                )

    evidences.sort(key=lambda e: (e.similarity, e.confidence), reverse=True)
    kept = evidences[:max_evidence]
    kept_sim = f"{kept[0].similarity:.2f}" if kept else "-"
    logger.debug(
        f"[retrieval_pipeline] retrieve: facts={len(facts)} obs={len(observations)} "
        f"exp={len(experiences)} ins={len(insights)} rel={bool(relationship)} "
        f"kept={len(kept)} top_sim={kept_sim}"
    )
    return kept, top_sim


# ── Cross verification ──

def _detect_contradictions(evidences: list[MemoryEvidence]) -> list[str]:
    """Direct fact-level conflicts: same category|key with a different value.
    Free-text observations are not contradiction-checked."""
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


async def cross_verify(evidences: list[MemoryEvidence], embed=None
                       ) -> tuple[list[MemoryEvidence], list[str], float]:
    """矛盾检测 + 一致性（批量编码余弦均值）。

    Returns (evidences, contradictions, consistency).
    """
    contradictions = _detect_contradictions(evidences)
    consistency = await _check_consistency(evidences, embed)
    return evidences, contradictions, consistency


async def _check_consistency(evidences: list[MemoryEvidence],
                             embed=None) -> float:
    """Mean pairwise cosine similarity of evidence contents, clipped to
    [0, 1]. One batch encode; without an embed engine the score is neutral.
    Similar → ~1.0; orthogonal topics → ~0.0."""
    if len(evidences) <= 1:
        return 1.0
    if not embed:
        return 0.5
    try:
        texts = [e.content for e in evidences]
        loop = asyncio.get_running_loop()
        vecs = await loop.run_in_executor(None, embed.encode, texts)
        sims = np.dot(vecs, vecs.T)
        iu = np.triu_indices(len(evidences), k=1)
        return float(np.clip(sims[iu].mean(), 0.0, 1.0))
    except Exception as e:
        logger.debug(f"[retrieval_pipeline] consistency check failed: {e}")
        return 0.5


# ── Context profiles ──

class ContextBuilder:
    """Render the same verified MemoryAnswer into different context strings
    according to the consumer's profile."""

    def build(self, profile: str, ma) -> str:
        """ma: MemoryAnswer-like object with answer/confidence/evidences/
        contradictions/needs_more_evidence fields. Returns empty string when
        ma is None or has no answer.
        """
        if ma is None or not getattr(ma, "answer", ""):
            return ""
        if profile == "agent1":
            return self._build_full(ma)
        if profile == "agent3":
            return self._build_light(ma)
        if profile == "agent2":
            return ""
        raise ValueError(f"unknown retrieval profile: {profile}")

    @staticmethod
    def _build_full(ma) -> str:
        """Agent 1 full context: confidence, contradictions, evidence caveat."""
        parts = [f"=== 记忆检索（置信度 {ma.confidence:.0%}）===", ma.answer]
        if ma.contradictions:
            parts.append("⚠️ 矛盾记忆：" + "；".join(ma.contradictions[:3])
                         + "（如需引用请先向用户确认）")
        if ma.needs_more_evidence or ma.confidence < 0.4:
            parts.append("（以上记忆证据不足，当作待确认信息，不要当作确定事实）")
        return "\n".join(parts)

    @staticmethod
    def _build_light(ma) -> str:
        """Agent 3 light context: compact, no confidence annotations."""
        facts = []
        experiences = []
        relationship_line = ""
        for e in ma.evidences:
            if e.is_contradicted:
                continue
            if e.source_type == "insight" or e.source_type == "observation":
                continue
            if e.source_type == "fact":
                facts.append(e)
            elif e.source_type == "experience":
                experiences.append(e)
            elif e.source_type == "relationship":
                if e.content.startswith("关系指标："):
                    relationship_line = e.content[len("关系指标："):]
                else:
                    relationship_line = e.content

        facts = facts[:3]
        experiences = experiences[:2]

        lines = ["=== 相关记忆 ==="]
        for e in facts:
            lines.append(f"- {e.content}")
        for e in experiences:
            lines.append(f"- {e.content}")
        if relationship_line:
            lines.append(f"关系：{relationship_line}")

        if len(lines) == 1:
            return ""
        return "\n".join(lines)
