"""Sleep/wake cycle: time-window logic, dream generation, state persistence."""

import logging
import os
import random
from datetime import datetime

logger = logging.getLogger(__name__)


class SleepManager:
    """Manages AI sleep/wake cycle, dream generation, and sleep state persistence."""

    def __init__(self, sleep_state_file: str, personality, ltm, provider):
        self._sleep_state_file = sleep_state_file
        self._personality = personality
        self._ltm = ltm
        self._provider = provider
        self._sleeping = self._load_sleep_state()

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    def _load_sleep_state(self) -> bool:
        try:
            with open(self._sleep_state_file) as f:
                return f.read().strip() == "1"
        except Exception as e:
            logger.warning(f"Failed to read sleep state: {e}")
            return False

    def _save_sleep_state(self) -> None:
        try:
            with open(self._sleep_state_file, "w") as f:
                f.write("1" if self._sleeping else "0")
        except Exception as e:
            logger.warning(f"Failed to save sleep state: {e}")

    def get_sleep_state(self) -> tuple[bool, str | None]:
        """Check if AI should sleep/wake. Returns (should_sleep, wake_message_or_None)."""
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

        # Nap window: 12:00-13:00
        if 12 <= hour < 13 and not self._sleeping:
            if random.random() < max(0.1, sleepiness):
                self._sleeping = True; self._save_sleep_state()
                logger.info(f"[sleep] nap trigger: sleepiness={sleepiness:.2f} hour={hour:.2f}")
                return True, "我去午睡一会儿...困了[困]"

        # Night sleep: 23:00-01:00
        if 23 <= hour or hour < 1:
            if not self._sleeping:
                if random.random() < max(0.3, sleepiness + 0.3):
                    self._sleeping = True; self._save_sleep_state()
                    logger.info(f"[sleep] night trigger: sleepiness={sleepiness:.2f} hour={hour:.2f}")
                    return True, "夜深了...我睡了，晚安[月亮]"

        # Wake from nap: 13:10-16:00
        if 13.16 <= hour < 16 and self._sleeping:
            wake_chance = 0.3 + (hour - 13.16) / 3.0
            wake_chance += max(0, e.arousal - 0.3) * 0.2
            wake_chance -= r * 0.1
            if random.random() < min(0.9, wake_chance):
                self._sleeping = False; self._save_sleep_state()
                dream = self.generate_dream()
                logger.info(f"[sleep] nap wake: arousal={e.arousal:.2f} dream={'yes' if dream else 'no'}")
                return False, f"睡醒了...{'做了个梦：' + dream if dream else '没做梦，睡得挺香'}"

        # Wake from night: 7:00-10:00
        if 7 <= hour < 10 and self._sleeping:
            wake_chance = 0.2 + (hour - 7) / 3.0
            wake_chance += max(0, e.arousal - 0.3) * 0.15
            wake_chance -= r * 0.1
            if random.random() < min(0.9, wake_chance):
                self._sleeping = False; self._save_sleep_state()
                dream = self.generate_dream()
                logger.info(f"[sleep] morning wake: arousal={e.arousal:.2f} dream={'yes' if dream else 'no'}")
                return False, f"早上好！{'我做了个梦：' + dream if dream else '睡得很好！'}"

        return False, None

    def generate_dream(self) -> str:
        """Generate a quick dream during sleep."""
        try:
            facts = self._ltm.get_all_active_facts(limit=5)
            exps = self._ltm.get_recent_experiences(limit=3)
            fact_str = " ".join(f"{f.fact_key}:{f.fact_value}" for f in facts)[:300]
            exp_str = " ".join(f"[{e.emotional_tone}]{e.summary}" for e in exps)[:300]
            prompt = (
                f"基于这些记忆碎片生成一段简短的梦境（1-2句话，第一人称，碎片化诗意）：\n"
                f"事实:{fact_str}\n经历:{exp_str}\n情绪:{self._personality.emotion.dominant_emotion}"
            )
            dream = self._provider.generate(
                [{"role": "user", "content": prompt}],
                stream=False, max_tokens=100,
            )
            self._personality.emotion.record_emotion_event(
                trigger=f"梦: {dream.strip()[:100]}",
                context=dream.strip()[:200],
            )
            # SL-111: save dream as experience
            dream_text = dream.strip()
            if dream_text:
                self._ltm.store_experience(
                    summary=f"梦境：{dream_text}",
                    tone=self._personality.emotion.dominant_emotion,
                    significance=0.3,
                    tags=["dream"],
                )
            logger.info(f"[dream] generated: {dream_text[:60]}")
            return dream_text
        except Exception:
            logger.debug("[dream] generation failed")
            return ""
