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
    REFLECTION_L2_PROMPT,
    REFLECTION_L3_PROMPT,
    EMOTION_ANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    def __init__(self, ltm: LongTermMemory, llm_generate_fn: callable,
                 embedding_engine=None):
        self.ltm = ltm
        self.llm = llm_generate_fn
        self._embed = embedding_engine
        self._pending_buffer: list = []
        self._seen_ids: set = set()  # #22: dedup
        self._consolidation_count = 0
        from memory.fact_checker import FactChecker
        self._fact_checker = FactChecker(embedding_engine)

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
        # #22: dedup by turn_id + role
        key = (turn.turn_id, turn.role)
        if key not in self._seen_ids:
            self._seen_ids.add(key)
            self._pending_buffer.append(turn)

    def consolidate(self, short_term: ConversationBuffer,
                    personality: Personality,
                    max_facts: int = 200,
                    max_experiences: int = 100,
                    max_reflections: int = 50) -> None:
        if not self._pending_buffer:
            self._prune(max_facts, max_experiences, max_reflections)
            return

        turn_text = self._format_turns(self._pending_buffer)
        logger.info(f"Consolidating {len(self._pending_buffer)} turns...")

        # #136: step-by-step with error isolation — each step independent
        errors = []

        # Step 1: Extract user facts
        try:
            self._extract_facts(turn_text)
        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
            errors.append("facts")

        # Step 2: Summarize experiences
        if len(turn_text) > 200:
            try:
                self._summarize_experience(turn_text, short_term)
            except Exception as e:
                logger.warning(f"Experience summarization failed: {e}")
                errors.append("experiences")

        # Step 3: Generate reflection — tiered L1/L2/L3 (#5)
        try:
            self._consolidation_count += 1
            if self._consolidation_count % 10 == 0:
                self._generate_reflection_l3(personality)
            elif self._consolidation_count % 3 == 0:
                self._generate_reflection_l2()
            else:
                self._generate_reflection_l1(personality)
        except Exception as e:
            logger.warning(f"Reflection generation failed: {e}")
            errors.append("reflections")

        # Step 4: Update relationship
        try:
            self._update_relationship(personality)
        except Exception as e:
            logger.warning(f"Relationship update failed: {e}")
            errors.append("relationship")

        # Step 5: Prune
        try:
            self._prune(max_facts, max_experiences, max_reflections)
        except Exception as e:
            logger.warning(f"Pruning failed: {e}")

        # Step 6: Embed new items
        try:
            self._embed_new_items()
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")

        if errors:
            logger.warning(f"Consolidation partial: {len(errors)} step(s) failed: {errors}")
            # P1: clear buffer on any error to avoid re-processing already-extracted facts
            self._pending_buffer.clear()
            self._seen_ids.clear()
            return

        self._pending_buffer.clear()
        self._seen_ids.clear()
        logger.info("Consolidation complete.")

    def analyze_sentiment(self, text: str) -> tuple[float, bool, float]:
        """Returns (sentiment, personal_sharing, topic_energy).
        #200: on failure, returns (0.0, False, 0.5) — safe neutral fallback
        that skips intimacy updates in _update_relationship."""
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
            new_facts = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if re.match(r'FACT\s*\|', line):  # #141: tolerate whitespace around |
                    parts = line.split("|")
                    if len(parts) >= 5:
                        _, category, key, value, conf_str = parts[:5]
                        importance = 0.5
                        if len(parts) >= 6:
                            try:
                                importance = float(parts[5])
                            except ValueError:
                                pass
                        fact_type = "user_fact"  # default
                        if len(parts) >= 7:
                            fact_type = parts[6].strip() or "user_fact"
                        try:
                            confidence = float(conf_str)
                        except ValueError:
                            confidence = 0.5
                        # #127: only store user_fact, skip agent_fact/system_fact
                        if fact_type != "user_fact":
                            logger.debug(f"Skipped non-user fact: {key} type={fact_type}")
                            continue
                        if confidence > 0.3:
                            category = category.strip()
                            key = key.strip()
                            value = value.strip()
                            self.ltm.store_fact(
                                category, key, value,
                                confidence, importance=importance,
                                fact_type="user_fact",  # #127
                            )
                            logger.debug(f"Stored fact: {key} = {value} (imp={importance})")
                            new_facts.append((category, key, value, confidence))

            # FactChecker: check new facts against existing ones for contradictions
            if self._fact_checker and new_facts:
                for cat, key, val, conf in new_facts:
                    similar = self.ltm.get_similar_facts(cat, key, limit=5)
                    from models.memory import UserFact
                    new_f = UserFact(category=cat, fact_key=key, fact_value=val, confidence=conf)
                    old_f = self._fact_checker.detect_contradiction(new_f, similar)
                    if old_f:
                        self._fact_checker.resolve(new_f, old_f, self.ltm)  # #207: pass ltm for sync wrappers
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

    def _generate_reflection_l1(self, personality: Personality) -> None:
        """L1: Basic reflection — facts and user discoveries. Every consolidation."""
        self._generate_reflection(personality)

    def _generate_reflection_l2(self) -> None:
        """L2: Pattern recognition — recurring behavior patterns. Every 3rd consolidation."""
        try:
            experiences = self.ltm.get_recent_experiences(limit=10)
            facts = self.ltm.get_all_active_facts(limit=15)
            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value}" for f in facts
            ) or "暂无"
            prompt = REFLECTION_L2_PROMPT.format(facts=fact_text, experiences=exp_text)
            result = self.llm(prompt, temperature=0.4)
            content = ""
            significance = 0.5
            related_ids = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("CONTENT:"):
                    content = line[len("CONTENT:"):].strip()
                elif line.startswith("SIGNIFICANCE:"):
                    try:
                        significance = float(line[len("SIGNIFICANCE:"):].strip())
                    except ValueError: pass
                elif line.startswith("RELATED_EXPERIENCES:"):
                    ids_str = line[len("RELATED_EXPERIENCES:"):].strip()
                    related_ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if content and significance > 0.3:
                self.ltm.store_reflection(content, "l2_pattern", related_ids, significance)
                logger.info(f"Stored L2 pattern: {content[:50]}")
        except Exception as e:
            logger.warning(f"L2 reflection failed: {e}")

    def _generate_reflection_l3(self, personality: Personality) -> None:
        """L3: Deep insight — psychological-level analysis. Every 10th consolidation."""
        try:
            experiences = self.ltm.get_recent_experiences(limit=20)
            reflections = self.ltm.get_recent_reflections(limit=10)
            facts = self.ltm.get_all_active_facts(limit=20)
            relationship = self.ltm.get_relationship()
            patterns = [r for r in reflections if r.insight_type == "l2_pattern"][:5]
            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value}" for f in facts
            ) or "暂无"
            pat_text = "\n".join(f"- {r.content}" for r in patterns) or "暂无"
            prompt = REFLECTION_L3_PROMPT.format(
                facts=fact_text, experiences=exp_text,
                relationship=relationship,
                current_emotion=personality.emotion.dominant_emotion,
                patterns=pat_text,
            )
            result = self.llm(prompt, temperature=0.5)
            content = ""
            significance = 0.5
            related_ids = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("CONTENT:"):
                    content = line[len("CONTENT:"):].strip()
                elif line.startswith("SIGNIFICANCE:"):
                    try:
                        significance = float(line[len("SIGNIFICANCE:"):].strip())
                    except ValueError: pass
                elif line.startswith("RELATED_EXPERIENCES:"):
                    ids_str = line[len("RELATED_EXPERIENCES:"):].strip()
                    related_ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if content and significance > 0.5:
                self.ltm.store_reflection(content, "l3_deep_insight", related_ids, significance)
                logger.info(f"Stored L3 insight: {content[:50]}")
        except Exception as e:
            logger.warning(f"L3 reflection failed: {e}")

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

    def _embed_new_items(self) -> None:
        """Batch encode new facts/experiences/reflections that lack embeddings."""
        if not self._embed or not self._embed.health_check():
            return

        from memory.embeddings import EmbeddingEngine
        try:
            with self.ltm.repo.db.get_connection() as conn:
                # Collect items without embeddings
                all_updates = []

                for table, text_cols in [
                    ("user_facts", ["category", "fact_key", "fact_value"]),
                    ("experiences", ["summary", "emotional_tone", "tags"]),
                    ("reflections", ["content"]),
                ]:
                    col_list = ", ".join(text_cols)
                    rows = conn.execute(
                        f"SELECT id, {col_list} FROM {table} "
                        "WHERE embedding IS NULL LIMIT 50"
                    ).fetchall()

                    if rows:
                        texts = []
                        targets = []
                        for row in rows:
                            rid = row["id"]
                            parts = [str(row[c] or "") for c in text_cols]
                            texts.append(" ".join(parts))
                            targets.append((table, rid))

                        vecs = self._embed.encode(texts)
                        for (tbl, rid), vec in zip(targets, vecs):
                            all_updates.append((tbl, rid, EmbeddingEngine.vec_to_bytes(vec)))

                if all_updates:
                    for tbl in ["user_facts", "experiences", "reflections"]:
                        tbl_updates = [(rid, emb) for t, rid, emb in all_updates if t == tbl]
                        if tbl_updates:
                            self.ltm.repo.bulk_update_embeddings(tbl, tbl_updates)
                    logger.info(f"[embed] encoded {len(all_updates)} new items")
        except Exception as e:
            logger.warning(f"[embed] batch encoding failed: {e}")

    @staticmethod
    def _format_turns(turns: list) -> str:
        return "\n".join(
            f"{'用户' if t.role == 'user' else '你'}: {t.content}"
            for t in turns
        )
