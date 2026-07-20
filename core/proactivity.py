"""Proactive behavior engine: scoring, topic selection, rate limiting."""

import json
import logging
import os
import random
import time
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


class ProactivityManager:
    """Manages when and what the AI proactively says, with rate limiting."""

    def __init__(self, personality, ltm, short_term,
                 state_dir: str | None = None, session_id: str = "default"):
        self._personality = personality
        self._ltm = ltm
        self._short_term = short_term
        self._last_explore_time: float = 0
        self._last_chat_time: float = 0
        self._consecutive_silents: int = 0   # F1: 连续 silent 决策次数（退避用）
        self._recent_topics: deque = deque(maxlen=5)  # #265: topic dedup
        # M-11: 限速/话题状态按 session 持久化（参照 .sleep_state 模式），
        # Web session 重建后限速不再清零
        self._state_file = (
            os.path.join(state_dir, f".proactivity_state.{session_id or 'default'}.json")
            if state_dir else None
        )
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted rate-limit/topic state; silently keep defaults on failure."""
        if not self._state_file:
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._last_explore_time = float(data.get("last_explore_time", 0))
            self._last_chat_time = float(data.get("last_chat_time", 0))
            self._consecutive_silents = int(data.get("consecutive_silents", 0))
            topics = data.get("recent_topics", [])
            if isinstance(topics, list):
                self._recent_topics.extend(str(t) for t in topics[-5:])
        except Exception as e:
            # M-11: 文件不存在/损坏时静默降级为默认值，不影响主流程
            if os.path.exists(self._state_file):
                logger.warning(f"[proactive] state load failed, using defaults: {e}")

    def _save_state(self) -> None:
        """Persist rate-limit/topic state; write failures never break the flow."""
        if not self._state_file:
            return
        try:
            data = {
                "last_explore_time": self._last_explore_time,
                "last_chat_time": self._last_chat_time,
                "consecutive_silents": self._consecutive_silents,
                "recent_topics": list(self._recent_topics),
            }
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[proactive] state save failed: {e}")

    def get_recent_topics(self) -> list:
        """Recent topics (oldest first), for prompt injection and tests."""
        return list(self._recent_topics)

    def record_topic(self, topic: str) -> None:
        """#177: 记录主路径（LLM 决策）实际选用的话题，供去重与 prompt 提示。

        已在队列中的话题移到最新位置，保持 MRU 语义；队列满时最老的淘汰。
        """
        topic = (topic or "").strip()
        if not topic:
            return
        if topic in self._recent_topics:
            self._recent_topics.remove(topic)
        self._recent_topics.append(topic)
        self._save_state()

    def calculate_proactivity(self, idle_duration: float) -> float:
        """Return 0.0-0.8 probability of initiating proactive chat."""
        e = self._personality.emotion
        r = getattr(e, 'resentment', 0.0)

        idle_thresholds = {
            "excited": 60, "joyful": 90, "surprised": 120,
            "engaged": 180, "content": 300, "trusting": 240, "anticipating": 150,
            "neutral": 360,
            "anxious": 90, "afraid": 180,
            "melancholy": 600, "sad": 900,
            "frustrated": 300, "angry": 480, "disgusted": 600,
        }
        min_idle = idle_thresholds.get(e.dominant_emotion, 300)
        min_idle += int(r * 300)

        if idle_duration < min_idle:
            return 0.0

        base = min(0.3, (idle_duration - min_idle) / 900.0)
        hour = datetime.now().hour
        time_mod = 0.2 if 10 <= hour <= 21 else 0.1 if 7 <= hour <= 22 else 0.0
        emotion_mod = e.arousal * 0.2
        if e.dominant_emotion in ("melancholy", "sad", "frustrated", "afraid"):
            emotion_mod -= 0.15
        rel = self._ltm.get_relationship()
        intimacy_mod = rel.get("intimacy", 0.3) * 0.15 + min(rel.get("familiarity", 0.3) * 0.1, 0.1)
        user_turns = [t for t in self._short_term.get_recent(6) if t.role == "user"][-3:]
        sentiment_mod = 0.0
        if user_turns:
            last = user_turns[-1].content
            if any(kw in last for kw in ["烦", "滚", "生气", "讨厌", "别烦", "不想", "别吵"]):
                sentiment_mod = -0.3
            elif any(kw in last for kw in ["哈哈", "开心", "好看", "棒", "不错", "喜欢", "好"]):
                sentiment_mod = 0.1
        goodbye = sum(1 for t in self._short_term.get_recent(6) if any(kw in t.content for kw in ["拜拜", "再见", "bye", "下次", "睡了", "晚安"]))
        short_c = sum(1 for t in user_turns if len(t.content) < 8)
        score = base + time_mod + emotion_mod + intimacy_mod + sentiment_mod - min(goodbye * 0.15, 0.3) - min(short_c * 0.08, 0.2)
        # F5: 长时间沉默疲劳——用户半小时以上没说话，逐步压低触发概率
        fatigue = min(0.3, max(0.0, (idle_duration - 1800.0) / 1800.0) * 0.1)
        score = max(0.0, min(0.8, score - fatigue))
        logger.debug(f"[proactive] score={score:.3f} idle={idle_duration:.0f}s emo={e.dominant_emotion} "
                     f"base={base:.3f} time={time_mod:.2f} emo={emotion_mod:+.2f} "
                     f"intimacy={intimacy_mod:+.2f} sentiment={sentiment_mod:+.2f} "
                     f"goodbye={min(goodbye*0.15,0.3):.2f} short={min(short_c*0.08,0.2):.2f}")
        return score

    def pick_proactive_topic(self) -> str:
        """Select a topic for proactive conversation initiation. (#265: dedup against recent topics)"""
        exps = self._ltm.get_recent_experiences(limit=3)
        facts = self._ltm.get_all_active_facts(limit=5)
        interests = getattr(self._personality.config, 'interests', [])
        topics = []

        if exps:
            topics.append(f"上次聊的: {exps[0].summary}")
        if facts:
            f = random.choice(facts)
            topics.append(f"关于用户的: {f.fact_key} = {f.fact_value}")
        if interests:
            topic = random.choice(interests)
            topics.append(f"聊点关于「{topic}」的")
        if not topics:
            hour = datetime.now().hour
            if 6 <= hour < 9:
                topics.append("早上好，聊聊今天的计划")
            elif 12 <= hour < 14:
                topics.append("午饭时间，聊聊吃了什么")
            elif 21 <= hour < 24:
                topics.append("夜深了，聊聊今天过得怎么样")
            else:
                topics.append("聊聊最近有什么新鲜事")

        # #265: filter out recently used topics, fall back to first candidate
        fresh = [t for t in topics if t not in self._recent_topics]
        chosen = random.choice(fresh) if fresh else topics[0]
        self._recent_topics.append(chosen)
        self._save_state()  # M-11: 话题变更随状态一起落盘
        logger.debug(f"[proactive] topic chosen={chosen[:40]} filtered={len(topics) - len(fresh)} recent={list(self._recent_topics)}")
        return chosen

    def check_rate_limit(self, action: str) -> bool:
        """Check rate limits (read-only, does not update timestamps)."""
        now = time.time()
        if action == "explore":
            if now - self._last_explore_time < 3600:
                logger.debug(f"[rate] explore blocked: {now - self._last_explore_time:.0f}s since last")
                return False
            return True
        elif action == "chat":
            if self._last_chat_time == 0:
                return True
            if now - self._last_chat_time < 1800:
                logger.debug(f"[rate] chat blocked: {now - self._last_chat_time:.0f}s since last")
                return False
            return True
        return True

    def record_rate_limit(self, action: str) -> None:
        """Record that an action was actually sent (updates timestamp)."""
        now = time.time()
        if action == "explore":
            self._last_explore_time = now
        elif action == "chat":
            self._last_chat_time = now
        # M-11: 状态变更后落盘，Web session 重建后可恢复
        self._save_state()

    # ── F1: silent 退避 ──

    def record_silent(self) -> None:
        """F1: InnerDrive 决定沉默时调用，连续 silent 次数 +1。"""
        self._consecutive_silents += 1
        # 状态持久化让退避在 session 重建后延续
        self._save_state()

    def reset_silents(self) -> None:
        """F1: 用户说话或主动消息真正发出后调用，退避清零。"""
        self._consecutive_silents = 0
        self._save_state()

    def silent_cooldown_seconds(self) -> float:
        """F1: 连续 n 次 silent 后的决策冷却秒数：60→120→240→…，封顶 1800s。"""
        if self._consecutive_silents <= 0:
            return 0.0
        return min(60.0 * (2 ** (self._consecutive_silents - 1)), 1800.0)
