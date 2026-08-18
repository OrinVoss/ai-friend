"""Inner drive state — the AI's persistent inner world (inner-drive-state.md).

二期：typed entries (care/curiosity/reflection/plan/idea) with a full
lifecycle (active → resolved/expired/decayed), emotion-linked surface
scoring, response-path semantic surfacing (surface_for_query), and
conversation-based resolution (resolve_matching).

Persisted per session as ``data/.inner_drive_state.{session_id}`` (same
per-session file pattern as ``.sleep_state``). v1 flat care-list files are
migrated on load. All failures (missing/corrupt file, write errors,
embedding errors) degrade gracefully — the inner world must never break
the main flow.
"""
import base64
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from memory.embeddings import EmbeddingEngine

logger = logging.getLogger(__name__)

VALID_TYPES = {"care", "curiosity", "reflection", "plan", "idea"}
TYPE_LABELS = {"care": "挂念", "curiosity": "好奇", "reflection": "反思",
               "plan": "计划", "idea": "灵感"}

PLAN_PIN_HOURS = 6          # plan 临期强制置顶的时间窗
FRESH_BONUS_HOURS = 24      # 新条目微弱加成的时间窗
DECAY_ARCHIVE_THRESHOLD = 0.2  # priority 低于此值自动归档（空谈沉底）


@dataclass
class DriveEntry:
    """一条内驱状态：AI 自己在意的事（inner-drive-state.md 第 2 节）。"""
    id: str = ""
    type: str = "care"           # care/curiosity/reflection/plan/idea
    content: str = ""
    priority: float = 0.5        # 0.0~1.0，浮现权重，动态调整
    source: str = "think_loop"   # think_loop / consolidation / memory_agent / user
    created_at: str = ""
    last_surfaced_at: str = ""
    surface_count: int = 0
    expires_at: str = ""         # ISO 时间或空；plan 类通常有明确时效
    status: str = "active"       # active / resolved / expired / decayed
    resolution: str = ""         # 解决时的记录——「完成了心事」的证据
    embedding: str = ""          # base64 编码的向量（用于语义浮现/对照解决）

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DriveEntry":
        known = {f for f in DriveEntry.__dataclass_fields__}
        entry = DriveEntry(**{k: v for k, v in d.items() if k in known})
        if entry.type not in VALID_TYPES:
            entry.type = "care"
        if entry.status not in ("active", "resolved", "expired", "decayed"):
            entry.status = "active"
        try:
            entry.priority = min(1.0, max(0.0, float(entry.priority)))
        except (TypeError, ValueError):
            entry.priority = 0.5
        return entry


def type_weights(emotion) -> dict:
    """情绪联动的类型权重：低落时挂念/反思上调，兴奋/好奇时灵感/好奇上调。"""
    w = {t: 1.0 for t in VALID_TYPES}
    if emotion is None:
        return w
    try:
        valence = float(getattr(emotion, "valence", 0.0) or 0.0)
        arousal = float(getattr(emotion, "arousal", 0.5) or 0.5)
    except (TypeError, ValueError):
        return w
    if valence < -0.2:
        w["care"] = w["reflection"] = 1.3
    if valence > 0.3 or arousal > 0.65:
        w["idea"] = w["curiosity"] = 1.3
    return w


class InnerDriveState:
    """内驱状态：类型化条目 + 生命周期 + 浮现规则（二期）。"""

    def __init__(self, session_id: str, max_entries: int = 20,
                 state_dir: str = "data", embedding_engine=None,
                 surface_top_k: int = 8, response_top_k: int = 3,
                 decay_rate: float = 0.9, similarity_threshold: float = 0.7):
        self._path = Path(state_dir) / f".inner_drive_state.{session_id}"
        try:
            self._max = max(1, int(max_entries))
        except (TypeError, ValueError):
            self._max = 20
        self._embed = embedding_engine
        self._surface_top_k = surface_top_k
        self._response_top_k = response_top_k
        self._decay_rate = decay_rate
        self._sim_threshold = similarity_threshold
        self._lock = threading.Lock()
        self._entries: list[DriveEntry] = []
        self._loaded = False

    # ── Read APIs ──

    def entries(self) -> list[str]:
        """活跃条目内容（旧接口，兼容一期调用方/测试）。"""
        return [e.content for e in self.active_entries()]

    def active_entries(self) -> list[DriveEntry]:
        with self._lock:
            self._load_once()
            return [e for e in self._entries if e.status == "active"]

    def surface(self, emotion=None, top_k: int | None = None) -> list[DriveEntry]:
        """独处时浮现：按 浮现分 = priority × 类型权重(情绪) × 时效加成 选 Top K。
        plan 临期强制置顶。被浮现但未行动的条目 priority 衰减——
        「老想到但一直不做的，多半是空谈」。"""
        with self._lock:
            self._load_once()
            self._refresh_statuses()
            now = datetime.now()
            weights = type_weights(emotion)
            scored = []
            for e in self._entries:
                if e.status != "active":
                    continue
                score = e.priority * weights.get(e.type, 1.0)
                if e.type == "plan" and e.expires_at:
                    hours = self._hours_until(e.expires_at, now)
                    if hours is not None and 0 <= hours <= PLAN_PIN_HOURS:
                        score += 100.0  # 约定不能错过
                age_h = self._hours_since(e.created_at, now)
                if age_h is not None and age_h <= FRESH_BONUS_HOURS:
                    score *= 1.1
                scored.append((score, e))
            scored.sort(key=lambda x: x[0], reverse=True)
            k = top_k or self._surface_top_k
            picked = [e for _, e in scored[:k]]
            for e in picked:
                e.surface_count += 1
                e.last_surfaced_at = now.isoformat(timespec="seconds")
                e.priority = round(e.priority * self._decay_rate, 4)
            self._archive_decayed()
            self._evict_if_needed()
            self._save_quiet()
            return picked

    def surface_for_query(self, query: str,
                          top_k: int | None = None) -> list[DriveEntry]:
        """对话时语义浮现：用户消息与活跃条目向量比对，超过阈值的 Top K。
        只读——响应路径的浮现不计 surface_count、不衰减。"""
        if self._embed is None or not query or not query.strip():
            return []
        vec = self._encode(query[:500])
        if vec is None:
            return []
        with self._lock:
            self._load_once()
            self._refresh_statuses()
            hits = []
            for e in self._entries:
                if e.status != "active" or not e.embedding:
                    continue
                sim = self._sim(vec, e.embedding)
                if sim is not None and sim >= self._sim_threshold:
                    hits.append((sim, e))
            hits.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in hits[: top_k or self._response_top_k]]

    # ── Write APIs ──

    def apply_updates(self, add: list | None = None,
                      remove: list | None = None,
                      source: str = "think_loop") -> None:
        """新增/移除条目。add 元素可以是字符串或
        {"content", "type", "priority", "expires_at"} 字典。"""
        with self._lock:
            self._load_once()
            if remove:
                drop = {str(x).strip() for x in remove}
                before = len(self._entries)
                self._entries = [e for e in self._entries
                                 if e.content not in drop]
                if len(self._entries) != before:
                    logger.info(f"[inner_drive_state] removed "
                                f"{before - len(self._entries)} entr(ies)")
            for item in add or []:
                entry = self._make_entry(item, source=source)
                if entry is None:
                    continue
                # 近重复去重（2026-08-18 监控发现"第三次挂科/挂了三次"并存）：
                # 精确相同总是去重；2-gram 覆盖率 ≥ 0.7 判近重复——
                # 仅限双方 ≥10 字符（短文本 shingle 集合太小，易误伤，
                # 如"旧同优先级/新同优先级"共享部首导致 0.75 的假命中）
                from utils import shingle_similarity
                if any(e.status == "active"
                       and (e.content == entry.content
                            or (len(e.content) >= 10 and len(entry.content) >= 10
                                and shingle_similarity(e.content, entry.content) >= 0.7))
                       for e in self._entries):
                    continue
                self._entries.append(entry)
                logger.info(f"[inner_drive_state] new {entry.type}: "
                            f"{entry.content[:60]} (source={source})")
            self._evict_if_needed()
            self._save_quiet()

    def resolve(self, entry_id: str, resolution: str = "") -> bool:
        """标记条目已解决——「完成了心事」的证据。"""
        with self._lock:
            self._load_once()
            for e in self._entries:
                if e.id == entry_id and e.status == "active":
                    e.status = "resolved"
                    e.resolution = resolution
                    logger.info(f"[inner_drive_state] resolved: "
                                f"{e.content[:50]} | {resolution[:50]}")
                    self._save_quiet()
                    return True
            return False

    def resolve_matching(self, text: str,
                         threshold: float | None = None) -> int:
        """对照解决（consolidation 调用）：对话文本与活跃条目语义比对，
        命中的标记 resolved。返回解决条数。"""
        if self._embed is None or not text or not text.strip():
            return 0
        vec = self._encode(text[:500])
        if vec is None:
            return 0
        thr = threshold if threshold is not None else self._sim_threshold
        with self._lock:
            self._load_once()
            self._refresh_statuses()
            resolved = []
            for e in self._entries:
                if e.status != "active" or not e.embedding:
                    continue
                sim = self._sim(vec, e.embedding)
                if sim is not None and sim >= thr:
                    e.status = "resolved"
                    e.resolution = f"对话中提及（相似度 {sim:.2f}）"
                    resolved.append(e)
            if resolved:
                for e in resolved:
                    logger.info(f"[inner_drive_state] resolved by conversation: "
                                f"{e.content[:50]}")
                self._save_quiet()
            return len(resolved)

    def record_outcome(self, entry_id: str, positive: bool) -> bool:
        """L4-6a: 反馈闭环。根据用户回应对被驱动的条目做奖惩。

        positive → 同类型活跃条目 priority +0.05（封顶 1.0）；
        negative → 同类型活跃条目 priority ×0.9；
        被驱动的条目标记 resolved，resolution 记录结果。
        """
        with self._lock:
            self._load_once()
            target = next((e for e in self._entries
                           if e.id == entry_id and e.status == "active"), None)
            if target is None:
                return False
            for e in self._entries:
                if e.status != "active" or e.type != target.type:
                    continue
                if positive:
                    e.priority = round(min(1.0, e.priority + 0.05), 4)
                else:
                    e.priority = round(e.priority * 0.9, 4)
            target.status = "resolved"
            target.resolution = f"用户回应：{'积极' if positive else '消极'}"
            logger.info(f"[inner_drive_state] outcome recorded: "
                        f"{target.content[:50]} positive={positive}")
            self._save_quiet()
            return True

    # ── Lifecycle helpers ──

    def _refresh_statuses(self) -> None:
        """过期检查：active 条目超过 expires_at → expired。"""
        now = datetime.now()
        for e in self._entries:
            if e.status == "active" and e.expires_at:
                hours = self._hours_until(e.expires_at, now)
                if hours is not None and hours < 0:
                    e.status = "expired"

    def _archive_decayed(self) -> None:
        for e in self._entries:
            if e.status == "active" and e.priority < DECAY_ARCHIVE_THRESHOLD:
                e.status = "decayed"

    def _evict_if_needed(self) -> None:
        """容量淘汰（二期，非 FIFO）：先清 resolved/expired/decayed，
        再清低 priority，最后才动旧的活跃条目。"""
        while len(self._entries) > self._max:
            inactive = [e for e in self._entries if e.status != "active"]
            if inactive:
                victim = inactive[0]  # 最旧的非活跃
            else:
                victim = min(self._entries,
                             key=lambda e: (e.priority, e.created_at))
            logger.info(f"[inner_drive_state] evicted ({victim.status}): "
                        f"{victim.content[:50]}")
            self._entries.remove(victim)

    # ── Entry construction ──

    def _make_entry(self, item, source: str) -> DriveEntry | None:
        if isinstance(item, str):
            content, etype, priority, expires_at = item, "care", 0.5, ""
        elif isinstance(item, dict):
            content = str(item.get("content", "") or "").strip()
            etype = str(item.get("type", "care"))
            if etype not in VALID_TYPES:
                etype = "care"
            try:
                priority = min(1.0, max(0.0, float(item.get("priority", 0.5))))
            except (TypeError, ValueError):
                priority = 0.5
            expires_at = str(item.get("expires_at", "") or "")
        else:
            return None
        content = content.strip()
        if not content:
            return None
        return DriveEntry(
            id=self._next_id(), type=etype, content=content,
            priority=priority, source=source,
            created_at=datetime.now().isoformat(timespec="seconds"),
            expires_at=expires_at,
            embedding=self._embed_text(content),
        )

    def _next_id(self) -> str:
        prefix = datetime.now().strftime("c_%Y%m%d_")
        n = sum(1 for e in self._entries if e.id.startswith(prefix)) + 1
        existing = {e.id for e in self._entries}
        while f"{prefix}{n:03d}" in existing:
            n += 1
        return f"{prefix}{n:03d}"

    # ── Embedding helpers ──

    def _embed_text(self, text: str) -> str:
        vec = self._encode(text)
        if vec is None:
            return ""
        return base64.b64encode(EmbeddingEngine.vec_to_bytes(vec)).decode("ascii")

    def _encode(self, text: str):
        if self._embed is None:
            return None
        try:
            vec = np.asarray(self._embed.encode_single(text), dtype=np.float32)
            norm = np.linalg.norm(vec)
            return vec / norm if norm > 0 else None
        except Exception as e:
            logger.debug(f"[inner_drive_state] encode failed: {e}")
            return None

    @staticmethod
    def _sim(query_vec, entry_b64: str) -> float | None:
        try:
            ev = EmbeddingEngine.bytes_to_vec(
                base64.b64decode(entry_b64), dim=len(query_vec))
            return float(np.dot(ev, query_vec))
        except Exception:
            return None

    # ── Time helpers ──

    @staticmethod
    def _hours_until(iso: str, now: datetime) -> float | None:
        try:
            return (datetime.fromisoformat(iso) - now).total_seconds() / 3600
        except (ValueError, TypeError):
            # #315: TypeError — LLM 写入带时区的 ISO 时间时 naive-aware 相减
            return None

    @staticmethod
    def _hours_since(iso: str, now: datetime) -> float | None:
        if not iso:
            return None
        try:
            return (now - datetime.fromisoformat(iso)).total_seconds() / 3600
        except (ValueError, TypeError):  # #315: 同上
            return None

    # ── Persistence ──

    def _load_once(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._entries = []
            return
        except Exception as e:
            logger.warning(f"[inner_drive_state] load failed "
                           f"({self._path}): {e}")
            self._entries = []
            return
        if isinstance(data.get("entries"), list):  # v2
            self._entries = [DriveEntry.from_dict(e)
                             for e in data["entries"]
                             if isinstance(e, dict) and e.get("content")]
        elif isinstance(data.get("care_list"), list):  # v1 → migrate
            self._entries = []
            for i, old in enumerate(data["care_list"], 1):
                if isinstance(old, dict) and old.get("content"):
                    self._entries.append(DriveEntry(
                        id=f"c_migrated_{i:03d}", type="care",
                        content=str(old["content"]), priority=0.5,
                        source="think_loop",
                        created_at=str(old.get("created_at", "")),
                    ))
            if self._entries:
                logger.info(f"[inner_drive_state] migrated {len(self._entries)} "
                            f"v1 care item(s) to typed entries")
        else:
            self._entries = []

    def _save_quiet(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"version": 2,
                            "entries": [e.to_dict() for e in self._entries]},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[inner_drive_state] save failed: {e}")



def create_inner_drive_state(config, session_id: str, embedding_engine=None):
    """InnerDriveState 单一创建点（session_factory 与 agent_wiring 共用）。

    消除两处重复的参数映射（原"初始化链断裂"：两处各自拼
    inner_drive_* 配置）。proactive_think_loop 关闭时返回 None，
    与调用方原行为一致。
    """
    if not getattr(config, "proactive_think_loop", True):
        return None
    return InnerDriveState(
        session_id=session_id or "default",
        max_entries=getattr(config, "inner_drive_care_list_size", 20),
        embedding_engine=embedding_engine,
        surface_top_k=getattr(config, "inner_drive_surface_top_k", 8),
        response_top_k=getattr(config, "inner_drive_surface_response_k", 3),
        decay_rate=getattr(config, "inner_drive_decay_rate", 0.9),
        similarity_threshold=getattr(
            config, "inner_drive_care_similarity_threshold", 0.7),
    )
