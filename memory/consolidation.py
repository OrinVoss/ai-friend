import concurrent.futures
import json
import logging
import re
from typing import Optional

from core.async_utils import _EXECUTOR, run_async
from memory.fact_checker import FactChecker
from memory.embeddings import EmbeddingEngine
from models.memory import UserFact, EMBEDDING_VERSION
from prompts.templates import safe_format

from memory.long_term import LongTermMemory
from memory.short_term import ConversationBuffer
from core.personality import Personality
from prompts.templates import (
    FACT_EXTRACTION_PROMPT,
    EXPERIENCE_SUMMARIZATION_PROMPT,
    INSIGHT_GENERATION_PROMPT,
    INSIGHT_L2_PROMPT,
    INSIGHT_L3_PROMPT,
    EMOTION_ANALYSIS_PROMPT,
    CARE_CLUE_PROMPT,
)

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    def __init__(self, ltm: LongTermMemory, llm_generate_fn: callable,
                 embedding_engine=None, timeout: float = 60.0,
                 config=None, inner_drive_state=None):
        self.ltm = ltm
        self.llm = llm_generate_fn
        self._timeout = timeout  # #184: independent timeout for LLM calls
        self._embed = embedding_engine
        self.config = config or {}
        # 内驱状态二期：consolidation 对照解决 + 线索写入（inner-drive-state.md §5）
        self._inner_drive_state = inner_drive_state
        self._pending_buffer: list = []
        self._seen_ids: set = set()  # #22: dedup
        self._consolidation_count = 0
        self._fact_checker = FactChecker(embedding_engine)
        # ML-001: Layer 1 Memory lifecycle (Observation -> Fact)。
        # 2026-07-18 完整上线：无条件创建，use_observation_fact 开关已删除。
        from memory.lifecycle import MemoryLifecycleManager
        self._lifecycle = MemoryLifecycleManager(
            ltm, config=self.config, embedding_engine=embedding_engine
        )

    def _call_llm(self, prompt: str, temperature: float = 0.2) -> str:
        """Call LLM with timeout protection. (#184)"""
        future = _EXECUTOR.submit(self.llm, prompt, temperature=temperature)
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            logger.warning(f"[consolidate] LLM timed out after {self._timeout}s")
            return ""
        except Exception as e:
            logger.warning(f"[consolidate] LLM call failed: {e}")
            return ""

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

        # ML-001: create a raw observation for this consolidation batch.
        # The same observation backs all facts extracted from this batch.
        # 2026-07-18 完整上线：无条件创建（原 use_observation_fact 开关已删）。
        lifecycle_obs_ids: list[int] = []
        try:
            start_id = min((t.turn_id for t in self._pending_buffer), default=None)
            end_id = max((t.turn_id for t in self._pending_buffer), default=None)
            obs = run_async(self._lifecycle.observe(
                content=turn_text,
                source_turn=end_id,
                episode_turn_start=start_id,
                episode_turn_end=end_id,
                created_by="consolidation",
            ))
            if obs and obs.id:
                lifecycle_obs_ids.append(obs.id)
        except Exception as e:
            logger.warning(f"[consolidate] observation creation failed: {e}")

        # Step 1: Extract user facts
        try:
            self._extract_facts(turn_text, observation_ids=lifecycle_obs_ids)
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

        # Step 3: Generate insight — tiered L1/L2/L3 (#5)
        # Layer 1 二期（2026-07-20）：输出由开放式 Reflection 改为结构化
        # Insight（hypothesis + evidence + confidence），落 insights_v2。
        try:
            self._consolidation_count += 1
            if self._consolidation_count % 10 == 0:
                self._generate_reflection_l3(personality)
            elif self._consolidation_count % 3 == 0:
                self._generate_reflection_l2()
            else:
                self._generate_reflection_l1(personality)
        except Exception as e:
            logger.warning(f"Insight generation failed: {e}")
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

        # Step 5.5: Layer 1 Memory lifecycle GC — 完整上线后无条件执行
        if self._consolidation_count % 5 == 0:
            try:
                run_async(self._lifecycle.garbage_collect())
            except Exception as e:
                logger.warning(f"[consolidate] lifecycle GC failed: {e}")

        # Step 6: Embed new items
        try:
            self._embed_new_items()
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")

        # Step 7: 内驱状态同步（二期，inner-drive-state.md 第 5 节）
        # 对照解决：对话中提及的挂念标记 resolved；线索写入：发现未完成
        # 的线索自动生成新条目。state 未接线时整步跳过。
        if self._inner_drive_state is not None:
            try:
                resolved = self._inner_drive_state.resolve_matching(turn_text)
                if resolved:
                    logger.info(f"[consolidate] resolved {resolved} care item(s) "
                                f"from conversation")
            except Exception as e:
                logger.warning(f"[consolidate] care resolve failed: {e}")
            try:
                self._extract_care_clues(turn_text)
            except Exception as e:
                logger.warning(f"[consolidate] care clue extraction failed: {e}")

        if errors:
            logger.warning(f"Consolidation partial: {len(errors)} step(s) failed: {errors}")
            # P1: clear buffer on any error to avoid re-processing already-extracted facts
            self._pending_buffer.clear()
            self._seen_ids.clear()
            return

        self._pending_buffer.clear()
        self._seen_ids.clear()
        logger.info("Consolidation complete.")

    def _extract_care_clues(self, turn_text: str) -> None:
        """内驱状态二期：从对话中提取「未完成的线索」写入挂念清单
        （source=consolidation）。LLM 输出 JSON，解析失败静默跳过。"""
        if not turn_text.strip():
            return
        prompt = safe_format(CARE_CLUE_PROMPT, text=turn_text[:3000])
        result = self._call_llm(prompt, temperature=0.2)
        if not result:
            return
        m = re.search(r'\{.*\}', result.strip(), re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else result.strip())
        except (json.JSONDecodeError, AttributeError):
            logger.debug(f"[consolidate] care clue JSON parse failed: "
                         f"{result[:100]}")
            return
        clues = data.get("clues")
        if not isinstance(clues, list) or not clues:
            return
        valid = [c for c in clues
                 if isinstance(c, dict) and str(c.get("content", "")).strip()]
        if valid:
            self._inner_drive_state.apply_updates(add=valid,
                                                  source="consolidation")
            logger.info(f"[consolidate] {len(valid)} care clue(s) added")

    def analyze_sentiment(self, text: str) -> tuple[float, bool, float]:
        """Returns (sentiment, personal_sharing, topic_energy).
        #200: on failure, returns (0.0, False, 0.5) — safe neutral fallback
        that skips intimacy updates in _update_relationship."""
        try:
            prompt = safe_format(EMOTION_ANALYSIS_PROMPT, text=text)
            result = self._call_llm(prompt, temperature=0.2)
            # TM-005: LLM may wrap JSON in markdown code fences; extract first
            # valid JSON object before passing to json.loads.
            m = re.search(r'\{[^}]+\}', result.strip(), re.DOTALL)
            raw = m.group(0) if m else result.strip()
            data = json.loads(raw)
            return (
                float(data.get("sentiment", 0)),
                bool(data.get("personal_sharing", False)),
                float(data.get("topic_energy", 0.5)),
            )
        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")
            return 0.0, False, 0.5

    def _extract_facts(self, turn_text: str,
                       observation_ids: Optional[list[int]] = None) -> None:
        try:
            prompt = safe_format(FACT_EXTRACTION_PROMPT, text=turn_text)
            result = self._call_llm(prompt, temperature=0.2)
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
                            new_facts.append((category, key, value, confidence, importance))
                            logger.debug(f"Extracted fact: {key} = {value} (imp={importance})")

            # FactChecker: check new facts against existing ones for contradictions.
            # 保持在写入前逐条检测：get_similar_facts 读 facts_v2，此时新事实
            # 尚未落库，检测语义与旧流程（先检测后批量写）一致。
            if self._fact_checker and new_facts:
                for cat, key, val, conf, _imp in new_facts:
                    similar = self.ltm.get_similar_facts(cat, key, limit=5)
                    new_f = UserFact(category=cat, fact_key=key, fact_value=val, confidence=conf)
                    old_f = self._fact_checker.detect_contradiction(new_f, similar)
                    if old_f:
                        self._fact_checker.resolve(new_f, old_f, self.ltm)  # #207: pass ltm for sync wrappers

            # ML-001 完整上线（2026-07-18）：单写 facts_v2 —— 每条 fact 经
            # lifecycle promote 落库（替代 #161 的 store_facts_bulk 旧表批量写；
            # 每批事实数量小，逐条写可接受）。upsert ON CONFLICT 自带 #217 复活语义。
            for cat, key, val, conf, imp in new_facts:
                try:
                    run_async(self._lifecycle.promote_fact(
                        observation_ids=observation_ids or [],
                        category=cat,
                        key=key,
                        value=val,
                        confidence=conf,
                        stability=0.5,
                        freshness=1.0,
                        importance=imp,
                        created_by="consolidation",
                    ))
                except Exception as e:
                    logger.warning(f"[consolidate] promote fact failed: {e}")
            if new_facts:
                logger.debug(f"Promoted {len(new_facts)} facts to facts_v2")
        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")

    def _summarize_experience(self, turn_text: str,
                               short_term: ConversationBuffer) -> None:
        try:
            prompt = safe_format(EXPERIENCE_SUMMARIZATION_PROMPT, text=turn_text)
            result = self._call_llm(prompt, temperature=0.3)

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

    # ── Insight generation（Layer 1 二期，2026-07-20）──
    # 方法名保留 _generate_reflection_l1/l2/l3（层级节奏与既有测试不变），
    # 输出统一走 INSIGHT_*_PROMPT → JSON → lifecycle.create_insight 落
    # insights_v2。JSON 解析失败兜底：log warning 跳过，不写垃圾数据。

    def _generate_reflection_l1(self, personality: Personality) -> None:
        """L1: 每次合并生成一条假设性 Insight（替代旧开放式 reflection）。"""
        try:
            experiences = self.ltm.get_recent_experiences(limit=5)
            facts = self.ltm.get_all_active_facts(limit=10)
            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value} (id={f.id})" for f in facts
            ) or "暂无"
            prompt = safe_format(INSIGHT_GENERATION_PROMPT,
                                 facts=fact_text, experiences=exp_text)
            result = self._call_llm(prompt, temperature=0.4)
            # min_confidence 沿用旧 L1 的 significance>0.4 门槛
            self._store_insight_from_json(result, min_confidence=0.4, level="L1")
        except Exception as e:
            logger.warning(f"L1 insight generation failed: {e}")

    def _generate_reflection_l2(self) -> None:
        """L2: 每 3 次合并，基于近期 insight 归纳行为模式假设。"""
        try:
            experiences = self.ltm.get_recent_experiences(limit=10)
            facts = self.ltm.get_all_active_facts(limit=15)
            recent_insights = self.ltm.get_recent_reflections(limit=5)  # 适配器：insights_v2
            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value} (id={f.id})" for f in facts
            ) or "暂无"
            insight_text = "\n".join(
                f"- {r.content}" for r in recent_insights
            ) or "暂无"
            prompt = safe_format(INSIGHT_L2_PROMPT, facts=fact_text,
                                 experiences=exp_text, insights=insight_text)
            result = self._call_llm(prompt, temperature=0.4)
            # 沿用旧 L2 的 significance>0.3 门槛
            self._store_insight_from_json(result, min_confidence=0.3, level="L2",
                                          default_type="pattern")
        except Exception as e:
            logger.warning(f"L2 insight generation failed: {e}")

    def _generate_reflection_l3(self, personality: Personality) -> None:
        """L3: 每 10 次合并，提出长期模式/深度动机假设。"""
        try:
            experiences = self.ltm.get_recent_experiences(limit=20)
            reflections = self.ltm.get_recent_reflections(limit=10)  # 适配器：insights_v2
            facts = self.ltm.get_all_active_facts(limit=20)
            relationship = self.ltm.get_relationship()
            patterns = [r for r in reflections if r.insight_type == "pattern"][:5]
            exp_text = "\n".join(
                f"- [{e.emotional_tone}] {e.summary} (id={e.id})"
                for e in experiences
            ) or "暂无"
            fact_text = "\n".join(
                f"- {f.fact_key}: {f.fact_value} (id={f.id})" for f in facts
            ) or "暂无"
            pat_text = "\n".join(f"- {r.content}" for r in patterns) or "暂无"
            prompt = safe_format(INSIGHT_L3_PROMPT,
                facts=fact_text, experiences=exp_text,
                relationship=relationship,
                current_emotion=personality.emotion.dominant_emotion,
                patterns=pat_text,
            )
            result = self._call_llm(prompt, temperature=0.5)
            # 沿用旧 L3 的 significance>0.5 门槛
            self._store_insight_from_json(result, min_confidence=0.5, level="L3")
        except Exception as e:
            logger.warning(f"L3 insight generation failed: {e}")

    def _store_insight_from_json(self, result: str, min_confidence: float,
                                 level: str,
                                 default_type: Optional[str] = None) -> None:
        """解析 LLM 的 Insight JSON 并经 lifecycle.create_insight 落库。
        解析失败/字段缺失/confidence 不达标：log warning 跳过，不写垃圾数据。
        evidence 只接受可解析为整数的事实 id（LLM 可能返回字符串或
        "fact_id_1" 形式，统一抽取数字）。"""
        if not result:
            return
        m = re.search(r'\{.*\}', result.strip(), re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else result.strip())
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"[consolidate] {level} insight JSON parse failed: "
                           f"{result[:100]}")
            return
        if not isinstance(data, dict):
            logger.warning(f"[consolidate] {level} insight not a JSON object, skipped")
            return
        hypothesis = str(data.get("hypothesis") or "").strip()
        if not hypothesis:
            logger.warning(f"[consolidate] {level} insight missing hypothesis, skipped")
            return
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= min_confidence:
            logger.debug(f"[consolidate] {level} insight below confidence gate "
                         f"({confidence:.2f} <= {min_confidence}), skipped")
            return
        evidence: list[int] = []
        raw_evidence = data.get("evidence") or []
        if isinstance(raw_evidence, (list, tuple)):
            for x in raw_evidence:
                if isinstance(x, (int, float)):
                    evidence.append(int(x))
                elif isinstance(x, str):
                    digits = re.findall(r'\d+', x)
                    if digits:
                        evidence.append(int(digits[0]))
        insight_type = data.get("insight_type") or default_type
        run_async(self._lifecycle.create_insight(
            hypothesis=hypothesis,
            evidence_fact_ids=evidence,
            insight_type=str(insight_type) if insight_type else None,
            confidence=confidence,
            needs_more_evidence=bool(data.get("needs_more_evidence", True)),
            created_by="consolidation",
        ))
        logger.info(f"Stored {level} insight ({insight_type}): {hypothesis[:50]}")

    def _update_relationship(self, personality: Personality) -> None:
        relationship = self.ltm.get_relationship()
        sentiment = 0.0
        personal_sharing = False

        if self._pending_buffer:
            last_user_turns = [
                t for t in self._pending_buffer[-3:] if t.role == "user"
            ]
            if last_user_turns:
                sentiment, personal_sharing, _ = self.analyze_sentiment(
                    last_user_turns[-1].content
                )

        dominant = personality.emotion.dominant_emotion
        negative_emotions = {"angry", "frustrated", "afraid", "anxious",
                             "disgusted", "melancholy", "sad"}
        updates: dict[str, float] = {}

        # familiarity: grows with every consolidation as we simply know each other longer
        new_familiarity = min(1.0, relationship.get("familiarity", 0.3) + 0.02)
        self.ltm.update_relationship("familiarity", new_familiarity)
        updates["familiarity"] = new_familiarity

        # trust: trusting emotion or positive sentiment builds it; negative emotions erode it
        if dominant == "trusting" or sentiment > 0.3:
            delta = 0.05 if dominant == "trusting" else sentiment * 0.05
            new_trust = min(1.0, relationship.get("trust", 0.3) + delta)
            self.ltm.update_relationship("trust", new_trust)
            updates["trust"] = new_trust
        elif dominant in negative_emotions:
            new_trust = max(0.0, relationship.get("trust", 0.3) - 0.02)
            self.ltm.update_relationship("trust", new_trust)
            updates["trust"] = new_trust

        # intimacy: personal sharing or warm/connected emotions deepen it
        if personal_sharing:
            new_intimacy = min(1.0, relationship.get("intimacy", 0.3) + 0.03)
            self.ltm.update_relationship("intimacy", new_intimacy)
            updates["intimacy"] = new_intimacy
        elif dominant in {"content", "engaged", "trusting"}:
            new_intimacy = min(1.0, relationship.get("intimacy", 0.3) + 0.02)
            self.ltm.update_relationship("intimacy", new_intimacy)
            updates["intimacy"] = new_intimacy

        # playfulness (fun in UI): positive/warm emotions lift it; negative emotions lower it
        positive_fun = {"joyful", "excited", "surprised", "content",
                        "engaged", "anticipating", "trusting"}
        if dominant in positive_fun:
            new_fun = min(1.0, relationship.get("playfulness", 0.3) + 0.02)
            self.ltm.update_relationship("playfulness", new_fun)
            updates["playfulness"] = new_fun
        elif dominant in negative_emotions:
            new_fun = max(0.0, relationship.get("playfulness", 0.3) - 0.02)
            self.ltm.update_relationship("playfulness", new_fun)
            updates["playfulness"] = new_fun

        if updates:
            summary = " ".join(f"{k}={v:.2f}" for k, v in updates.items())
            logger.info(f"[consolidate] relationship updated: {summary} emotion={dominant}")

    def _prune(self, max_facts: int, max_experiences: int, max_reflections: int) -> None:
        pruned_f = run_async(self.ltm.repo.prune_facts(max_facts))
        pruned_e = run_async(self.ltm.repo.prune_experiences(max_experiences))
        pruned_r = run_async(self.ltm.repo.prune_reflections(max_reflections))
        if pruned_f or pruned_e or pruned_r:
            logger.info(f"Pruned: {pruned_f} facts, {pruned_e} experiences, {pruned_r} insights")

    def _embed_new_items(self) -> None:
        """Batch encode rows lacking embeddings across the embeddable memory tables."""
        if not self._embed or not self._embed.health_check():
            return

        try:
            async def _do_embed():
                all_updates = []
                # H-08: 可嵌入表清单（#285: 补 facts_v2 / observations；
                # 2026-07-18 Layer 1 完整上线：user_facts 已归档，移除；
                # 2026-07-20 Layer 1 二期：reflections 已归档，换 insights_v2）
                tables = [
                    ("experiences", ["summary", "emotional_tone", "tags"]),
                    ("insights_v2", ["hypothesis"]),
                    ("facts_v2", ["category", "fact_key", "fact_value"]),
                    ("observations", ["content"]),
                ]
                for table, text_cols in tables:
                    col_list = ", ".join(text_cols)
                    # Read candidates inside the cursor, then RELEASE it before
                    # encoding and before bulk_update_embeddings — the bulk
                    # call acquires the same connection lock, so holding the
                    # cursor across it self-deadlocks (found 2026-07-16; the
                    # old code timed out after 60s on every batch).
                    async with self.ltm.repo.db.cursor() as c:
                        # H-08: 只挑选本 session 的行
                        await c.execute(
                            f"SELECT id, {col_list} FROM {table} "
                            "WHERE (embedding IS NULL OR embedding_version != ?)"
                            " AND session_id = ? LIMIT 50",
                            (EMBEDDING_VERSION, self.ltm.repo.session_id),
                        )
                        rows = await c.fetchall()
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
                    for tbl, _ in tables:
                        tbl_updates = [(rid, emb) for t, rid, emb in all_updates if t == tbl]
                        if tbl_updates:
                            await self.ltm.repo.bulk_update_embeddings(tbl, tbl_updates)
                    logger.info(f"[embed] encoded {len(all_updates)} new items")
            run_async(_do_embed())
        except Exception as e:
            logger.warning(f"[embed] batch encoding failed: {type(e).__name__}: {e}")

    @staticmethod
    def _format_turns(turns: list) -> str:
        return "\n".join(
            f"{'用户' if t.role == 'user' else '你'}: {t.content}"
            for t in turns
        )
