import json
import logging
import re
from typing import Optional

from memory.long_term import LongTermMemory
from memory.short_term import ConversationBuffer
from core.personality import Personality
from prompts.templates import (
    FACT_EXTRACTION_PROMPT,
    EXPERIENCE_SUMMARIZATION_PROMPT,
    REFLECTION_PROMPT,
    EMOTION_ANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    def __init__(self, ltm: LongTermMemory, llm_generate_fn: callable):
        self.ltm = ltm
        self.llm = llm_generate_fn
        self._pending_buffer: list = []
        self._consolidation_count = 0

    def should_consolidate(self, turn_count: int, emotional_intensity: float,
                           idle_duration: float, config) -> bool:
        if turn_count > 0 and turn_count % config.consolidation_interval == 0:
            logger.debug(f"[consolidate] trigger: interval turn={turn_count}")
            return True
        if emotional_intensity > 0.7:
            logger.debug(f"[consolidate] trigger: intensity={emotional_intensity:.2f}")
            return True
        if len(self._pending_buffer) >= 10:
            logger.debug(f"[consolidate] trigger: buffer_full size={len(self._pending_buffer)}")
            return True
        if idle_duration > 120 and self._pending_buffer:
            logger.debug(f"[consolidate] trigger: idle idle={idle_duration:.0f}s")
            return True
        return False

    def add_pending(self, turn) -> None:
        self._pending_buffer.append(turn)

    def consolidate(self, short_term: ConversationBuffer,
                    personality: Personality,
                    max_facts: int = 200,
                    max_experiences: int = 100,
                    max_reflections: int = 50) -> None:
        if not self._pending_buffer:
            # Still prune even without new turns
            self._prune(max_facts, max_experiences, max_reflections)
            return

        turn_text = self._format_turns(self._pending_buffer)
        logger.info(f"Consolidating {len(self._pending_buffer)} turns...")

        # Step 1: Extract user facts
        self._extract_facts(turn_text)

        # Step 2: Summarize experiences
        if len(turn_text) > 200:
            self._summarize_experience(turn_text, short_term)

        # Step 3: Generate reflection (every consolidation)
        self._generate_reflection(personality)

        # Step 4: Update relationship (lightweight, no LLM)
        self._update_relationship(personality)

        # Step 5: Prune to limits
        self._prune(max_facts, max_experiences, max_reflections)

        # Step 6: Clear pending
        self._pending_buffer.clear()
        logger.info("Consolidation complete.")

    def analyze_sentiment(self, text: str) -> tuple[float, bool, float]:
        """Returns (sentiment, personal_sharing, topic_energy)"""
        try:
            prompt = EMOTION_ANALYSIS_PROMPT.format(text=text)
            result = self.llm(prompt, temperature=0.2)
            data = json.loads(result.strip())
            return (
                float(data.get("sentiment", 0)),
                bool(data.get("personal_sharing", False)),
                float(data.get("topic_energy", 0.5)),
            )
        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")
            return 0.0, False, 0.5

    def _extract_facts(self, turn_text: str) -> None:
        try:
            prompt = FACT_EXTRACTION_PROMPT.format(text=turn_text)
            result = self.llm(prompt, temperature=0.2)
            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("FACT|"):
                    parts = line.split("|")
                    if len(parts) >= 5:
                        _, category, key, value, conf_str = parts[:5]
                        importance = 0.5
                        if len(parts) >= 6:
                            try:
                                importance = float(parts[5])
                            except ValueError:
                                pass
                        try:
                            confidence = float(conf_str)
                        except ValueError:
                            confidence = 0.5
                        if confidence > 0.3:
                            self.ltm.store_fact(
                                category.strip(), key.strip(), value.strip(),
                                confidence, importance=importance,
                            )
                            logger.debug(f"Stored fact: {key} = {value} (imp={importance})")
        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")

    def _summarize_experience(self, turn_text: str,
                               short_term: ConversationBuffer) -> None:
        try:
            prompt = EXPERIENCE_SUMMARIZATION_PROMPT.format(text=turn_text)
            result = self.llm(prompt, temperature=0.3)

            summary = ""
            tone = "neutral"
            significance = 0.5
            importance = 0.5
            tags = []

            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("SUMMARY:"):
                    summary = line[len("SUMMARY:"):].strip()
                elif line.startswith("TONE:"):
                    tone = line[len("TONE:"):].strip()
                elif line.startswith("SIGNIFICANCE:"):
                    try:
                        significance = float(line[len("SIGNIFICANCE:"):].strip())
                    except ValueError:
                        pass
                elif line.startswith("IMPORTANCE:"):
                    try:
                        importance = float(line[len("IMPORTANCE:"):].strip())
                    except ValueError:
                        pass
                elif line.startswith("TAGS:"):
                    tags_raw = line[len("TAGS:"):].strip()
                    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            if summary and significance > 0.3:
                start_id = min((t.turn_id for t in self._pending_buffer), default=None)
                end_id = max((t.turn_id for t in self._pending_buffer), default=None)
                self.ltm.store_experience(
                    summary, tone, significance, tags, start_id, end_id, importance
                )
                logger.info(f"Stored experience ({significance:.2f}): {summary[:50]}")
        except Exception as e:
            logger.warning(f"Experience summarization failed: {e}")

    def _generate_reflection(self, personality: Personality) -> None:
        try:
            experiences = self.ltm.get_recent_experiences(limit=5)
            reflections = self.ltm.get_recent_reflections(limit=3)
            facts = self.ltm.get_all_active_facts(limit=10)
            relationship = self.ltm.get_relationship()

            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            ref_text = "\n".join(
                f"- {r.content}" for r in reflections
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value}" for f in facts
            ) or "暂无"

            prompt = REFLECTION_PROMPT.format(
                experiences=exp_text,
                reflections=ref_text,
                facts=fact_text,
                current_emotion=personality.emotion.dominant_emotion,
                relationship=relationship,
            )
            result = self.llm(prompt, temperature=0.4)

            insight_type = "user_discovery"
            content = ""
            significance = 0.5
            related_ids = []

            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("TYPE:"):
                    insight_type = line[len("TYPE:"):].strip()
                elif line.startswith("CONTENT:"):
                    content = line[len("CONTENT:"):].strip()
                elif line.startswith("SIGNIFICANCE:"):
                    try:
                        significance = float(line[len("SIGNIFICANCE:"):].strip())
                    except ValueError:
                        pass
                elif line.startswith("RELATED_EXPERIENCES:"):
                    ids_str = line[len("RELATED_EXPERIENCES:"):].strip()
                    related_ids = [
                        int(x.strip()) for x in ids_str.split(",")
                        if x.strip().isdigit()
                    ]

            if content and significance > 0.4:
                self.ltm.store_reflection(content, insight_type, related_ids, significance)
                logger.info(f"Stored reflection ({insight_type}): {content[:50]}")
        except Exception as e:
            logger.warning(f"Reflection generation failed: {e}")

    def _update_relationship(self, personality: Personality) -> None:
        relationship = self.ltm.get_relationship()
        sentiment = 0  # default neutral

        if self._pending_buffer:
            last_user_turns = [
                t for t in self._pending_buffer[-3:] if t.role == "user"
            ]
            if last_user_turns:
                sentiment, personal_sharing, _ = self.analyze_sentiment(
                    last_user_turns[-1].content
                )
                if personal_sharing:
                    new_val = min(1.0, relationship.get("intimacy", 0.3) + 0.03)
                    self.ltm.update_relationship("intimacy", new_val)

        new_familiarity = min(1.0, relationship.get("familiarity", 0.3) + 0.02)
        self.ltm.update_relationship("familiarity", new_familiarity)

        if sentiment > 0.3:
            new_trust = min(1.0, relationship.get("trust", 0.3) + sentiment * 0.05)
            self.ltm.update_relationship("trust", new_trust)

    def _prune(self, max_facts: int, max_experiences: int, max_reflections: int) -> None:
        pruned_f = self.ltm.repo.prune_facts(max_facts)
        pruned_e = self.ltm.repo.prune_experiences(max_experiences)
        pruned_r = self.ltm.repo.prune_reflections(max_reflections)
        if pruned_f or pruned_e or pruned_r:
            logger.info(f"Pruned: {pruned_f} facts, {pruned_e} experiences, {pruned_r} reflections")

    @staticmethod
    def _format_turns(turns: list) -> str:
        return "\n".join(
            f"{'用户' if t.role == 'user' else '你'}: {t.content}"
            for t in turns
        )
