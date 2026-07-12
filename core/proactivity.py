"""Proactive behavior engine: scoring, topic selection, rate limiting."""

import logging
import random
import time
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


class ProactivityManager:
    """Manages when and what the AI proactively says, with rate limiting."""

    def __init__(self, personality, ltm, short_term):
        self._personality = personality
        self._ltm = ltm
        self._short_term = short_term
        self._last_explore_time: float = 0
        self._last_chat_time: float = 0
        self._recent_topics: deque = deque(maxlen=5)  # #265: topic dedup

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
        score = max(0.0, min(0.8, score))
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
