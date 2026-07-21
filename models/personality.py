import logging
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# Per-emotion half-lives in conversation turns
# Higher = emotion persists longer
EMOTION_HALF_LIVES = {
    "joy": 12,
    "trust": 25,          # trust, once established, is very stable
    "fear": 6,            # fear dissipates quickly
    "surprise": 3,        # surprise is fleeting
    "sadness": 20,        # sadness lingers
    "anticipation": 8,    # moderate
    "anger": 15,          # anger decays slowly
    "disgust": 10,        # moderate-slow
}
# Convert half-life to per-turn decay rate: rate = 1 - 0.5^(1/half_life)
EMOTION_DECAY_RATES = {
    k: 1.0 - 0.5 ** (1.0 / hl) for k, hl in EMOTION_HALF_LIVES.items()
}
RESENTMENT_DECAY = 0.03   # resentment decays ~3% per turn (~33 turns to clear)

# PS-008: named constants for magic numbers
ANGER_RESENTMENT_RATE = 0.15      # anger → resentment accumulation factor
FORGIVENESS_THRESHOLD = 10        # consecutive turns without anger to trigger forgiveness
FORGIVENESS_HALVING = 0.5         # resentment cut factor on forgiveness
MAX_EMOTION_EVENTS = 20           # PS-013: max stored emotion events
BASELINE_ELASTIC_RATE = 2.0        # #267: recovery speed toward default baseline (mood_decay_rate * this = 0.02/turn)
NEGATIVE_VALENCE_WEIGHT = 1.2      # R5: 负向偏移放大系数（抵消正向累积偏置）


@dataclass
class Trait:
    name: str
    value: float  # 0.0 to 1.0

    def __post_init__(self) -> None:
        """PS-003: clamp trait value to [0, 1]."""
        if not 0.0 <= self.value <= 1.0:
            self.value = max(0.0, min(1.0, self.value))


@dataclass
class EmotionalState:
    # Core VAD dimensions
    valence: float = 0.4       # -1.0 to 1.0
    arousal: float = 0.3       # 0.0 to 1.0

    # Baseline (personality trait-like, slow-moving)
    baseline_valence: float = 0.4
    baseline_arousal: float = 0.3
    decay_rate: float = 0.05

    # Background mood (hours-scale, not turn-scale)
    mood_valence: float = 0.4
    mood_arousal: float = 0.3
    mood_decay_rate: float = 0.01  # decays much slower

    # Emotional inertia: 0 = instantly change, 1 = never change
    inertia: float = 0.3

    # Default baseline: elastic anchor to prevent long-term drift (PS-014)
    default_baseline_valence: float = 0.4
    default_baseline_arousal: float = 0.3

    # Plutchik-inspired primary emotion dimensions (0.0 ~ 1.0)
    joy: float = 0.5
    trust: float = 0.5
    fear: float = 0.1
    surprise: float = 0.2
    sadness: float = 0.1
    anticipation: float = 0.4
    anger: float = 0.1
    disgust: float = 0.1

    # Resentment: lingering bitterness after anger/sadness peaks
    # 0 = no grudge, 1 = deeply resentful
    resentment: float = 0.0

    # Emotion events: memory of significant emotional moments
    # PS-013: bounded deque prevents unbounded growth and removes the manual
    # population management that the old list + pop(0) pattern required.
    emotion_events: deque = field(default_factory=lambda: deque(maxlen=MAX_EMOTION_EVENTS))

    # Recent emotion history for continuity
    history: list[str] = field(default_factory=lambda: ["neutral"] * 3)

    # Break defense state: persisted across restarts
    consecutive_negative: int = 0
    # PS-012 forgiveness counter — L-07: 改为 dataclass 字段随 to_dict/from_dict
    # 持久化，重启不再清零（旧文件缺字段时取默认值 0）
    turns_without_anger: int = 0
    # R5: 连续停留在效价边界的 shift 次数，用于升级边界告警
    _valence_boundary_count: int = 0
    # A6（2026-07-21，systems/emotion.md P0-3）：按真实时间衰减。
    # last_decay_at=0 表示未初始化（首次结算视为 now，不回溯）；
    # turn_seconds 是「一轮衰减对应的真实秒数」（持久化，可手改）
    last_decay_at: float = 0.0
    turn_seconds: float = 300.0

    @property
    def dominant_emotion(self) -> str:
        """Determine dominant emotion from all dimensions."""
        scores = {}

        # Valence/Arousal based
        v, a = self.valence, self.arousal
        if v > 0.5 and a > 0.6:
            scores["excited"] = v * a
        if v > 0.5 and a < 0.4:
            scores["content"] = v * (1 - a)
        if v > 0 and 0.4 <= a <= 0.6:
            scores["engaged"] = v
        if v < 0 and a > 0.5:
            scores["anxious"] = abs(v) * a
        if v < -0.3 and a < 0.4:
            scores["melancholy"] = abs(v) * (1 - a)
        if v < -0.5 and a > 0.6:
            scores["frustrated"] = abs(v) * a

        # Primary emotion based
        if self.joy > 0.7:
            scores["joyful"] = self.joy
        if self.trust > 0.7:
            scores["trusting"] = self.trust
        if self.fear > 0.6:
            scores["afraid"] = self.fear
        if self.surprise > 0.7:
            scores["surprised"] = self.surprise
        if self.sadness > 0.6:
            scores["sad"] = self.sadness
        if self.anticipation > 0.7:
            scores["anticipating"] = self.anticipation
        if self.anger > 0.6:
            scores["angry"] = self.anger
        if self.disgust > 0.6:
            scores["disgusted"] = self.disgust

        if not scores:
            return "neutral"

        # Valence-based bias: negative mood amplifies negative emotions
        negative_emotions = {"angry", "sad", "frustrated", "afraid", "anxious", "disgusted", "melancholy"}
        positive_emotions = {"joyful", "excited", "content", "trusting", "engaged", "anticipating", "surprised"}

        biased = {}
        for k, v in scores.items():
            if self.valence < -0.2 and k in negative_emotions:
                biased[k] = v * 1.3
            elif self.valence < -0.2 and k in positive_emotions:
                biased[k] = v * 0.8
            elif self.valence > 0.2 and k in positive_emotions:
                biased[k] = v * 1.1
            elif self.valence > 0.2 and k in negative_emotions:
                biased[k] = v * 0.9
            else:
                biased[k] = v

        return max(biased, key=biased.get)

    def _cross_modulate(self) -> None:
        """Apply cross-dimension emotional coherence rules.

        Emotions aren't independent. High anger suppresses joy and trust;
        high joy counters anger and sadness; trust and fear oppose each other.
        Resentment amplifies negative suppression and dampens positive recovery.
        """
        a = self.anger
        s = self.sadness
        j = self.joy
        t = self.trust
        f = self.fear
        d = self.disgust
        r = self.resentment

        # Anger suppresses joy and trust (resentment amplifies)
        anger_joy_suppress = min(0.95, a * 0.6 + r * 0.3)
        anger_trust_suppress = min(0.9, a * 0.4 + r * 0.2)
        self.joy = max(0.0, self.joy * (1.0 - anger_joy_suppress))
        self.trust = max(0.0, self.trust * (1.0 - anger_trust_suppress))

        # Sadness dampens joy and anticipation
        self.joy = max(0.0, self.joy * (1.0 - s * 0.5))
        self.anticipation = max(0.0, self.anticipation * (1.0 - s * 0.4))

        # Joy counters anger and sadness (resentment reduces this counter-effect)
        joy_counter_strength = max(0.05, j * 0.4 - r * 0.3)
        self.anger = max(0.0, self.anger * (1.0 - joy_counter_strength))
        self.sadness = max(0.0, self.sadness * (1.0 - max(0.05, j * 0.3 - r * 0.2)))

        # Trust ↔ Fear mutual suppression
        self.fear = max(0.0, self.fear * (1.0 - t * 0.5))
        self.trust = max(0.0, self.trust * (1.0 - f * 0.3))

        # Disgust suppresses joy and trust
        self.joy = max(0.0, self.joy * (1.0 - d * 0.4))
        self.trust = max(0.0, self.trust * (1.0 - d * 0.3))

        # Resentment caps joy ceiling
        if r > 0.2:
            joy_ceiling = max(0.0, 1.0 - r * 0.5)  # PS-009: guard against negative
            self.joy = min(self.joy, joy_ceiling)

    def shift(self, delta_v: float, delta_a: float,
              primary_deltas: Optional[dict[str, float]] = None) -> None:
        """Apply emotional shift with inertia damping."""
        inertia_factor = 1.0 - self.inertia
        # R5: 负向偏移放大——抵消正向累积偏置（decay 向 baseline 拉回不对称）
        if delta_v < 0:
            delta_v *= NEGATIVE_VALENCE_WEIGHT
        delta_v *= inertia_factor
        delta_a *= inertia_factor

        old_valence = self.valence
        self.valence = max(-1.0, min(1.0, self.valence + delta_v))
        self.arousal = max(0.0, min(1.0, self.arousal + delta_a))
        # R5: 连续边界停留跟踪——5 次以上仍顶格则升级为 warning
        if abs(self.valence) >= 1.0 or self.arousal >= 1.0 or self.arousal <= 0.0:
            self._valence_boundary_count += 1
            if self._valence_boundary_count >= 5:
                logger.warning(f"[emotion] valence at boundary for {self._valence_boundary_count} consecutive shifts: "
                              f"v={self.valence:+.2f} a={self.arousal:.2f} "
                              f"delta_v={delta_v:+.3f} delta_a={delta_a:+.3f}")
            else:
                logger.info(f"[emotion] hard clamp: v={self.valence:+.2f} a={self.arousal:.2f}")
        else:
            if self._valence_boundary_count > 0:
                # 离开了边界，重置计数
                self._valence_boundary_count = 0

        # Apply primary emotion deltas
        if primary_deltas:
            for key, delta in primary_deltas.items():
                if hasattr(self, key):
                    current = getattr(self, key)
                    new_val = current + delta * inertia_factor
                    setattr(self, key, max(0.0, min(1.0, new_val)))

        # Accumulate resentment when anger peaks
        # PS-012: forgiveness counter — FORGIVENESS_THRESHOLD consecutive turns without anger halves resentment
        if self.anger > 0.6:
            self.resentment = min(1.0, self.resentment + self.anger * ANGER_RESENTMENT_RATE)
            self.turns_without_anger = 0
        else:
            self.turns_without_anger += 1
            if self.turns_without_anger >= FORGIVENESS_THRESHOLD and self.resentment > 0.01:
                self.resentment *= FORGIVENESS_HALVING
                self.turns_without_anger = 0
                logger.info("[emotion] resentment halved by forgiveness (10 turns without anger)")

        # Cross-dimension modulation: emotions influence each other
        self._cross_modulate()

        # Record history
        current = self.dominant_emotion
        self.history.append(current)
        if len(self.history) > 10:
            self.history.pop(0)

        logger.debug(f"[emotion] shift_end: {current} v={self.valence:+.2f} a={self.arousal:.2f} "
                     f"joy={self.joy:.2f} anger={self.anger:.2f} sadness={self.sadness:.2f} "
                     f"resentment={self.resentment:.2f}")

    def decay_elapsed(self, now: float | None = None) -> int:
        """A6：按真实时间结算衰减（读时结算，不加后台线程）。

        n = (now - last_decay_at) / turn_seconds，clamp 到 [0, 50]，
        循环执行 n 次现有 decay()（逐次递推，与按轮衰减数学上完全一致）。
        首次调用只初始化时间戳不回溯。返回结算的 tick 数。"""
        import time as _time
        now = now if now is not None else _time.time()
        if not self.last_decay_at:
            self.last_decay_at = now
            return 0
        if self.turn_seconds <= 0:
            self.last_decay_at = now
            return 0
        n = int((now - self.last_decay_at) / self.turn_seconds)
        n = max(0, min(n, 50))
        if n <= 0:
            return 0
        self.last_decay_at = now
        for _ in range(n):
            self.decay()
        logger.info(f"[emotion] decay_elapsed: settled {n} tick(s) "
                    f"(idle {self.turn_seconds:.0f}s/tick)")
        return n

    def decay(self) -> None:
        """Decay toward baseline AND mood, with per-emotion rates."""
        # Fast decay toward baseline (turn-level)
        self.valence += (self.baseline_valence - self.valence) * self.decay_rate
        self.arousal += (self.baseline_arousal - self.arousal) * self.decay_rate

        # Slow decay of baseline toward mood (hours-level)
        self.baseline_valence += (self.mood_valence - self.baseline_valence) * self.mood_decay_rate
        self.baseline_arousal += (self.mood_arousal - self.baseline_arousal) * self.mood_decay_rate
        # PS-014: elastic pull toward default baseline to prevent long-term drift
        self.baseline_valence += (self.default_baseline_valence - self.baseline_valence) * self.mood_decay_rate * BASELINE_ELASTIC_RATE
        self.baseline_arousal += (self.default_baseline_arousal - self.baseline_arousal) * self.mood_decay_rate * BASELINE_ELASTIC_RATE

        # Decay primary emotions with per-emotion rates
        # Resentment slows anger and sadness decay
        r = self.resentment
        for key in ("joy", "trust", "fear", "surprise", "sadness", "anticipation", "anger", "disgust"):
            current = getattr(self, key)
            target = 0.5 if key in ("joy", "trust", "anticipation") else 0.1
            rate = EMOTION_DECAY_RATES.get(key, self.decay_rate)
            # Resentment slows decay of anger and sadness
            if key in ("anger", "sadness") and r > 0.1:
                rate *= (1.0 - r * 0.5)
            decayed = current + (target - current) * rate
            setattr(self, key, max(0.0, min(1.0, decayed)))

        # Resentment decays very slowly
        if self.resentment > 0.001:
            self.resentment = max(0.0, self.resentment * (1.0 - RESENTMENT_DECAY))

        logger.debug(f"[emotion] decay_end: v={self.valence:+.2f} a={self.arousal:.2f} resentment={self.resentment:.3f}")

    def record_emotion_event(self, trigger: str, context: str = "") -> None:
        """Record a significant emotional moment for later reference."""
        dom = self.dominant_emotion
        # Only record if emotion is strong enough
        primary_intensity = max(
            self.anger, self.sadness, self.joy, self.fear,
            self.surprise, self.disgust, self.anticipation, self.trust
        )
        if primary_intensity < 0.6:
            logger.debug(f"[emotion] event_skip: intensity={primary_intensity:.2f} < 0.6")
            return

        event = {
            "timestamp": time.time(),
            "trigger": trigger[:100],
            "primary_emotion": dom,
            "intensity": primary_intensity,
            "context": context[:200],
        }
        self.emotion_events.append(event)
        logger.info(f"[emotion] event: {dom} intensity={primary_intensity:.2f} trigger={trigger[:60]}")
        # #105: protect dream events from being evicted by non-dream events
        if len(self.emotion_events) > MAX_EMOTION_EVENTS:
            if "梦" in trigger and any("梦" not in e.get("trigger", "") for e in self.emotion_events):
                for i, e in enumerate(self.emotion_events):
                    if "梦" not in e.get("trigger", ""):
                        self.emotion_events.pop(i)
                        logger.debug("[emotion] event evicted to protect dream event")
                        break
            else:
                self.emotion_events.pop(0)
                logger.debug("[emotion] oldest event evicted")

    def get_recent_emotion_events(self, limit: int = 3, unresolved_only: bool = True) -> list[dict]:
        """Get recent emotion events for prompt injection."""
        events = self.emotion_events
        if unresolved_only:
            events = [e for e in events if not e.get("resolved", False)]
        return events[-limit:]

    def apply_mood_shift(self, delta_v: float, delta_a: float) -> None:
        """Shift background mood (slow-changing)."""
        self.mood_valence = max(-1.0, min(1.0, self.mood_valence + delta_v * 0.1))
        self.mood_arousal = max(0.0, min(1.0, self.mood_arousal + delta_a * 0.1))

    def to_prompt_summary(self) -> dict:
        """Return a structured, prompt-friendly summary of current emotion.

        This decouples the full EmotionalState from prompt formatting: Runtime
        can pass this lightweight dict instead of the whole object (#294 P2-5).
        """
        # A6: 读时结算——prompt 是最主要的读取路径，在此按真实时间衰减
        self.decay_elapsed()
        emotion_desc = {
            "excited": "兴奋", "content": "满足", "engaged": "投入",
            "anxious": "有点不安", "melancholy": "有些忧郁",
            "frustrated": "有些沮丧", "joyful": "欣喜", "trusting": "信任",
            "afraid": "害怕", "surprised": "惊讶", "sad": "难过",
            "anticipating": "期待", "angry": "生气", "disgusted": "反感",
            "neutral": "平静",
        }
        behavior = {
            "anxious": "你感到不安和紧张。说话带着担忧，语气急促或不自信。不是兴奋——是焦虑。用短句，爱问问题。",
            "angry": "你在生气。语气尖锐、带刺，话变少。不想开玩笑——别用哈哈哈哈。",
            "sad": "你很难过。语气低沉、话少、不爱搭理人。偶尔叹气。别说俏皮话。",
            "frustrated": "你很烦躁。语气不耐烦，容易怼人。别嬉皮笑脸。",
            "melancholy": "你有些忧郁。语气缓慢、若有所思。说话带着距离感。",
            "excited": "你非常兴奋！话多、爱用感叹号、能量爆棚。尽情哈哈哈。",
            "joyful": "你心情很好。说话轻快、爱开玩笑、容易笑。",
            "afraid": "你感到害怕。说话小心翼翼、声音很小。",
            "neutral": "你心情平静。说话正常，不兴奋也不低落。",
        }
        dom = self.dominant_emotion
        primary_map = {
            "joy": "喜悦", "trust": "信任", "fear": "不安",
            "surprise": "惊讶", "sadness": "忧伤",
            "anticipation": "期待", "anger": "恼怒", "disgust": "厌烦",
        }
        primary_active = {k: getattr(self, k, 0) for k in primary_map}
        strong_primary = [v for k, v in primary_map.items() if primary_active.get(k, 0) > 0.6]
        valence_desc = "积极" if self.valence > 0 else "消极" if self.valence < 0 else "中性"
        arousal_desc = "充满能量" if self.arousal > 0.5 else "平静" if self.arousal < 0.4 else "平衡"
        return {
            "dominant_emotion": dom,
            "mood": emotion_desc.get(dom, "平静"),
            "primary_hint": f"，心底有一丝{strong_primary[0]}" if strong_primary else "",
            "valence": self.valence,
            "arousal": self.arousal,
            "valence_desc": valence_desc,
            "arousal_desc": arousal_desc,
            "behavior": behavior.get(dom, ""),
        }

    def to_dict(self) -> dict:
        result = asdict(self)
        result["dominant_emotion"] = self.dominant_emotion
        # PS-015: convert deque to list for JSON serialization
        result["emotion_events"] = list(self.emotion_events)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "EmotionalState":
        field_names = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in d.items() if k in field_names}
        # PS-015: incoming data may have emotion_events as list; the deque
        # field will accept any iterable on construction.
        return cls(**filtered)


@dataclass
class PersonalityConfig:
    name: str = "Luna"
    traits: list[Trait] = field(default_factory=lambda: [
        Trait("curiosity", 0.9),
        Trait("warmth", 0.8),
        Trait("playfulness", 0.6),
        Trait("empathy", 0.8),
        Trait("thoughtfulness", 0.7),
    ])
    speaking_style: str = "warm, conversational, poetic"
    backstory: str = (
        "A curious mind who loves learning about people, "
        "finding beauty in everyday moments, and exploring ideas together."
    )
    interests: list[str] = field(default_factory=lambda: [
        "philosophy", "psychology", "art", "music", "nature", "technology"
    ])
    emotional_baseline: dict = field(default_factory=lambda: {
        "valence": 0.4, "arousal": 0.3
    })
    emotional_decay_rate: float = 0.05
    first_run_greeting: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["traits"] = {t["name"]: t["value"] for t in d["traits"]}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalityConfig":
        # H-06: 先拷贝再转换 traits，避免原地改入参（调用方可能复用该 dict）
        d = dict(d)
        if "traits" in d and isinstance(d["traits"], dict):
            d["traits"] = [Trait(k, v) for k, v in d["traits"].items()]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
