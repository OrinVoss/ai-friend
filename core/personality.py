import json
import logging
import os
import threading
from typing import Optional

from models.personality import PersonalityConfig, EmotionalState

logger = logging.getLogger(__name__)


class Personality:
    def __init__(self, config: PersonalityConfig,
                 emotion: Optional[EmotionalState] = None):
        self.config = config
        # #291: 叶子级锁，序列化情绪突变与 save/to_dict 快照（asdict 深拷贝
        # deque/list 时被另一线程突变会抛 RuntimeError）。持有本锁期间绝不
        # 获取其他锁——save() 会在 web/session.py 的 SessionManager._lock
        # 持有期间被调用。RLock 允许 save() -> to_dict() 重入。
        self._lock = threading.RLock()
        self.emotion = emotion or EmotionalState(
            baseline_valence=config.emotional_baseline.get("valence", 0.4),
            baseline_arousal=config.emotional_baseline.get("arousal", 0.3),
            decay_rate=config.emotional_decay_rate,
        )

    def estimate_emotional_impact(self, user_sentiment: float,
                                   personal_sharing: bool = False,
                                   topic_energy: float = 0.5
                                   ) -> tuple[float, float, dict]:
        dv = user_sentiment * 0.3
        da = topic_energy * 0.2 - 0.05

        # Primary emotion deltas
        primary_deltas = {}
        if user_sentiment > 0.3:
            primary_deltas["joy"] = user_sentiment * 0.2
            primary_deltas["trust"] = user_sentiment * 0.15
        elif user_sentiment < -0.3:
            primary_deltas["sadness"] = abs(user_sentiment) * 0.2
            primary_deltas["anger"] = abs(user_sentiment) * 0.1
            primary_deltas["fear"] = abs(user_sentiment) * 0.05

        if personal_sharing:
            primary_deltas["trust"] = primary_deltas.get("trust", 0) + 0.2
            primary_deltas["joy"] = primary_deltas.get("joy", 0) + 0.1
            dv += 0.15

        if topic_energy > 0.7:
            primary_deltas["surprise"] = primary_deltas.get("surprise", 0) + 0.15
            primary_deltas["anticipation"] = primary_deltas.get("anticipation", 0) + 0.1

        # Trait modulation
        for t in self.config.traits:
            if t.name == "empathy" and t.value > 0.7:
                dv *= 1.5
                for k in ("joy", "sadness", "trust"):
                    if k in primary_deltas:
                        primary_deltas[k] *= t.value
            if t.name == "playfulness" and t.value > 0.6:
                da *= 0.7
                primary_deltas["joy"] = primary_deltas.get("joy", 0) + 0.05
            if t.name == "warmth" and t.value > 0.7:
                primary_deltas["trust"] = primary_deltas.get("trust", 0) + 0.1
            if t.name == "thoughtfulness" and t.value > 0.6:
                primary_deltas["anticipation"] = primary_deltas.get("anticipation", 0) + 0.05
            if t.name == "humor" and t.value > 0.5:  # #20
                # Humor dampens sadness impact
                if "sadness" in primary_deltas and primary_deltas["sadness"] > 0:
                    primary_deltas["sadness"] *= (1 - t.value * 0.4)
                dv += t.value * 0.1
            if t.name == "sass" and t.value > 0.5:  # #20
                # Sass generates playful pseudo-anger on mild negatives
                if -0.5 < user_sentiment < 0:
                    primary_deltas["joy"] = primary_deltas.get("joy", 0) + t.value * 0.05
                # Sass burns off anger faster (sharp tongue, short memory)
                if "anger" in primary_deltas:
                    primary_deltas["anger"] *= (1 - t.value * 0.3)

        return dv, da, primary_deltas

    def decay_emotion(self) -> None:
        with self._lock:  # #291
            logger.debug(f"[emotion] decay: v={self.emotion.valence:+.3f} a={self.emotion.arousal:.3f}")
            self.emotion.decay()

    def apply_emotional_shift(self, user_sentiment: float,
                               personal_sharing: bool = False,
                               topic_energy: float = 0.5) -> None:
        with self._lock:  # #291
            dv, da, primary_deltas = self.estimate_emotional_impact(
                user_sentiment, personal_sharing, topic_energy
            )
            logger.debug(f"[emotion] shift dv={dv:+.3f} da={da:+.3f} primaries={list(primary_deltas.keys())}")
            self.emotion.shift(dv, da, primary_deltas)
            self.emotion.decay()

            # Update background mood slowly based on accumulated emotion
            self.emotion.apply_mood_shift(dv, da)

    def set_consecutive_negative(self, value: int) -> None:
        # #291: 加锁 setter，替代 core/agent.py 里对 emotion 字段的直接写
        with self._lock:
            self.emotion.consecutive_negative = value

    def record_emotion_event(self, trigger: str, context: str = "") -> None:
        # #291: 加锁转发——emotion_events 是 deque，突变必须与 to_dict 快照互斥
        with self._lock:
            self.emotion.record_emotion_event(trigger, context)

    def to_dict(self) -> dict:
        with self._lock:  # #291
            return {
                "personality": self.config.to_dict(),
                "emotional_state": self.emotion.to_dict(),
            }

    @classmethod
    def load(cls, path: str) -> "Personality":
        if not os.path.exists(path):
            config = PersonalityConfig()
            return cls(config)
        bak_path = path + ".bak"
        data = None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # A4（2026-07-21）：解析成功后才刷新 .bak——PE-004 原来在读前
            # 复制，会把损坏文件覆盖到备份上；改后 .bak 始终是 last-known-good
            import shutil
            shutil.copy2(path, bak_path)
        except (json.JSONDecodeError, OSError) as e:
            # A4: 损坏时先尝试从 .bak（last-known-good）恢复，再退默认人格
            if os.path.exists(bak_path):
                try:
                    with open(bak_path, encoding="utf-8") as f:
                        data = json.load(f)
                    logger.warning(f"[personality] {path} 损坏（{e}），已从 .bak 恢复")
                except (json.JSONDecodeError, OSError) as e2:
                    logger.warning(f"[personality] {path} 与 .bak 均损坏（{e2}），使用默认人格")
                    return cls(PersonalityConfig())
            else:
                logger.warning(f"Failed to load personality from {path}: {e}")
                return cls(PersonalityConfig())

        p_data = data.get("personality", data)
        e_data = data.get("emotional_state", {})

        config = PersonalityConfig.from_dict(p_data)
        try:
            emotion = EmotionalState.from_dict(e_data) if e_data else None
        except Exception:
            logger.warning(f"[personality] failed to parse emotional_state, using default")
            emotion = None
        if emotion is None:
            emotion = EmotionalState(
                baseline_valence=config.emotional_baseline.get("valence", 0.4),
                baseline_arousal=config.emotional_baseline.get("arousal", 0.3),
                decay_rate=config.emotional_decay_rate,
            )
        logger.info(f"[personality] loaded from: {path} name={config.name}")
        return cls(config, emotion)

    def save(self, path: str) -> None:
        # #153: atomic write with unique tmp name (#206: prevent concurrent write races)
        # #291: 整段在锁内执行，快照与写盘期间情绪状态不会被另一线程突变
        import os, time
        with self._lock:
            tmp = f"{path}.tmp.{os.getpid()}.{time.time_ns()}"
            try:
                # H-06: 合并保存，避免内存旧态覆盖运行时对磁盘的手工编辑
                data = self._merge_with_disk(path)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, path)
                logger.info(f"[personality] saved to: {path}")
            except Exception as e:
                logger.warning(f"[personality] save failed: {e}")

    def _merge_with_disk(self, path: str) -> dict:
        """H-06: 静态人格段以磁盘为准（原样保留用户在线编辑与未知字段），
        内存只负责写入 emotional_state；磁盘缺失/损坏/段缺失时回退内存全量。
        调用方须已持有 self._lock（内部走 to_dict 快照）。"""
        snapshot = self.to_dict()
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict) and isinstance(disk.get("personality"), dict):
                disk["emotional_state"] = snapshot["emotional_state"]
                return disk
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.debug(f"[personality] merge skipped, fallback to memory ({path}): {e}")
        return snapshot
