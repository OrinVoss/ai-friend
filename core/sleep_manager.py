"""Sleep/wake cycle: time-window logic, dream generation, state persistence.

SL-001: sleep state file is namespaced per session_id so concurrent CLI/Web
sessions no longer share a single global `.sleep_state`.
SL-002: `_sleeping` transitions are guarded by a threading.Lock so two
proactive ticks cannot race the nap/night/wake windows into a torn state
(H-03 同型: 本对象会被不同事件循环使用——RuntimeDriver 守护线程的 loop
与 web proactive loop——asyncio.Lock 跨 loop 会失效/报错，故用 threading.Lock
只保护同步临界区，持锁期间绝不 await)。
SL-010: `generate_dream` is async so the proactive loop can `await` it
instead of blocking the executor thread on `provider.generate()`.
"""

import asyncio
import logging
import os
import random
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class SleepManager:
    """Manages AI sleep/wake cycle, dream generation, and sleep state persistence."""

    def __init__(self, sleep_state_file: str, personality, ltm, provider,
                 session_id: str = "default"):
        self._sleep_state_file = sleep_state_file
        self._session_id = session_id
        self._personality = personality
        self._ltm = ltm
        self._provider = provider
        # SL-002: guard _sleeping transitions against concurrent proactive ticks
        # H-03 同型: threading.Lock——跨事件循环可用；只保护同步临界区
        self._lock = threading.Lock()
        self._sleeping = self._load_sleep_state()
        # #167: cooldown to prevent rapid sleep/wake cycling
        self._last_transition_time = 0.0
        self._MIN_SLEEP_INTERVAL = 600  # 10 minutes minimum between transitions

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    def _load_sleep_state(self) -> bool:
        try:
            with open(self._sleep_state_file) as f:
                return f.read().strip() == "1"
        except FileNotFoundError:
            logger.debug(f"[sleep] state file not found, assuming awake: {self._sleep_state_file}")
            return False
        except Exception as e:
            logger.warning(f"Failed to read sleep state: {e}")
            return False

    def _save_sleep_state(self) -> None:
        try:
            with open(self._sleep_state_file, "w") as f:
                f.write("1" if self._sleeping else "0")
        except Exception as e:
            logger.warning(f"Failed to save sleep state: {e}")

    async def get_sleep_state(self) -> tuple[bool, str | None]:
        """Check if AI should sleep/wake. Returns (should_sleep, wake_message_or_None).

        SL-002: the window-check + transition + persistence is one synchronous
        critical section under `_lock` (threading.Lock), so two concurrent ticks
        cannot both flip `_sleeping` and overwrite each other's saved state.
        H-03 同型: dream generation awaits OUTSIDE the lock — 持锁期间绝不 await。
        """
        now = datetime.now()
        hour = now.hour + now.minute / 60.0
        e = self._personality.emotion
        r = getattr(e, 'resentment', 0.0)

        # Emotion-driven sleepiness (0-1)
        sleepiness = 0.0
        if e.dominant_emotion in ("sad", "melancholy"):
            sleepiness += 0.4
        if e.arousal < 0.3:
            sleepiness += 0.3
        if e.dominant_emotion in ("excited", "joyful"):
            sleepiness -= 0.2
        sleepiness += r * 0.2

        # 同步临界区：只读/改状态并持久化；三个唤醒窗口按小时互斥，
        # 用 wake_kind 记录触发的唤醒类型，梦境在锁外生成
        wake_kind: str | None = None
        with self._lock:
            # #167: cooldown guard — don't transition if too soon after last change
            if time.time() - self._last_transition_time < self._MIN_SLEEP_INTERVAL:
                return False, None

            # Nap window: 12:00-13:00
            if 12 <= hour < 13 and not self._sleeping:
                if random.random() < max(0.1, sleepiness):
                    self._sleeping = True; self._save_sleep_state()
                    self._last_transition_time = time.time()
                    logger.info(f"[sleep] nap trigger: sleepiness={sleepiness:.2f} hour={hour:.2f}")
                    return True, "我去午睡一会儿...困了[困]"

            # Night sleep: 23:00-01:00
            if 23 <= hour or hour < 1:
                if not self._sleeping:
                    if random.random() < max(0.3, sleepiness + 0.3):
                        self._sleeping = True; self._save_sleep_state()
                        self._last_transition_time = time.time()
                        logger.info(f"[sleep] night trigger: sleepiness={sleepiness:.2f} hour={hour:.2f}")
                        return True, "夜深了...我睡了，晚安[月亮]"

            # Wake from nap: 13:10-16:00
            if 13.16 <= hour < 16 and self._sleeping:
                wake_chance = 0.3 + (hour - 13.16) / 3.0
                wake_chance += max(0, e.arousal - 0.3) * 0.2
                wake_chance -= r * 0.1
                if random.random() < min(0.9, wake_chance):
                    self._sleeping = False; self._save_sleep_state()
                    self._last_transition_time = time.time()
                    wake_kind = "nap"

            # Wake from night: 7:00-10:00
            if 7 <= hour < 10 and self._sleeping:
                wake_chance = 0.2 + (hour - 7) / 3.0
                wake_chance += max(0, e.arousal - 0.3) * 0.15
                wake_chance -= r * 0.1
                # SL-011: guarantee wake-up as the window nears its end
                if hour >= 9.5:
                    wake_chance = 1.0
                if random.random() < min(0.9, wake_chance):
                    self._sleeping = False; self._save_sleep_state()
                    self._last_transition_time = time.time()
                    wake_kind = "morning"

            # SL-011: hard fail-safe — if still sleeping past the normal wake window,
            # force wake-up between 10:00-11:00 so the AI never sleeps forever.
            if 10 <= hour < 11 and self._sleeping:
                self._sleeping = False; self._save_sleep_state()
                self._last_transition_time = time.time()
                wake_kind = "forced"

        # 锁外：生成梦境（await）并拼接唤醒消息
        if wake_kind is not None:
            dream = await self.generate_dream()
            has_dream = 'yes' if dream else 'no'
            if wake_kind == "nap":
                logger.info(f"[sleep] nap wake: arousal={e.arousal:.2f} dream={has_dream}")
                return False, f"睡醒了...{'做了个梦：' + dream if dream else '没做梦，睡得挺香'}"
            if wake_kind == "morning":
                logger.info(f"[sleep] morning wake: arousal={e.arousal:.2f} dream={has_dream}")
                return False, f"早上好！{'我做了个梦：' + dream if dream else '睡得很好！'}"
            logger.info(f"[sleep] forced morning wake: arousal={e.arousal:.2f} dream={has_dream}")
            return False, f"太阳都晒屁股了才醒…{'做了个梦：' + dream if dream else '睡过头了！'}"

        return False, None

    async def generate_dream(self) -> str:
        """Generate a quick dream during sleep.

        SL-010: now async — `provider.generate()` is awaited via `run_in_executor`
        so the proactive loop no longer blocks an executor thread on a sync HTTP call.
        """
        try:
            facts = self._ltm.get_all_active_facts(limit=5)
            exps = self._ltm.get_recent_experiences(limit=3)
            fact_str = " ".join(f"{f.fact_key}:{f.fact_value}" for f in facts)[:300]
            exp_str = " ".join(f"[{e.emotional_tone}]{e.summary}" for e in exps)[:300]
            prompt = (
                f"基于这些记忆碎片生成一段简短的梦境（1-2句话，第一人称，碎片化诗意）：\n"
                f"事实:{fact_str}\n经历:{exp_str}\n情绪:{self._personality.emotion.dominant_emotion}"
            )
            dream = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._provider.generate(
                    [{"role": "user", "content": prompt}],
                    stream=False, max_tokens=100, source="dream",
                ),
            )
            # #291: 经 Personality 的加锁转发方法写 emotion_events deque
            self._personality.record_emotion_event(
                trigger=f"梦: {dream.strip()[:100]}",
                context=dream.strip()[:200],
            )
            # SL-111: save dream as experience
            dream_text = dream.strip()
            if dream_text:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._ltm.store_experience(
                        summary=f"梦境：{dream_text}",
                        tone=self._personality.emotion.dominant_emotion,
                        significance=0.3,
                        tags=["dream"],
                    ),
                )
            logger.info(f"[dream] generated: {dream_text[:60]}")
            return dream_text
        except Exception:
            logger.debug("[dream] generation failed")
            return ""
