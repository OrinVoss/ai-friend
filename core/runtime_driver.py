"""Shared runtime driver (unified-pipeline P2).

Time-driven behavior — sleep/wake transitions, dreams, proactive chat and
explore ticks — belongs to the engine, not to a frontend. This loop was
extracted verbatim-semantics from `web/server.py::_proactive_loop` so the
CLI runs the exact same rhythm as the Web.

The driver talks to a `ConversationEngine` (blocking LLM calls always go
through an executor) and emits cleaned events through a `Frontend`;
sync frontends are called directly, async callbacks are awaited.
"""
import asyncio
import inspect
import logging
import random
import threading
import time
from functools import partial
from typing import Optional

from core.conversation_engine import ConversationEngine, Frontend

logger = logging.getLogger(__name__)


class RuntimeDriver:
    """Drives one engine's sleep/proactivity ticks for one frontend.

    Two hosting modes:
    - Web: `asyncio.create_task(driver.run())` in the server's event loop;
      cancellation stops the loop.
    - CLI: `driver.start_in_thread()` spawns a daemon thread with its own
      event loop; `driver.stop()` ends it.
    """

    IDLE_FLOOR_SECONDS = 30        # no proactivity below this idle time
    TICK_ASLEEP = 30               # tick while the agent is asleep
    TICK_COOLDOWN = 5              # tick while in cooldown / below idle floor
    TICK_NORMAL = 15               # regular tick
    TICK_ERROR = 30                # backoff after a tick error
    SLEEP_MSG_COOLDOWN_TICKS = 60  # cooldown ticks after a sleep/wake message
    SLEEP_TRANSITION_TICKS = 120   # 10 min between sleep-state transitions
    PROACTIVE_COOLDOWN_TICKS = 12  # cooldown ticks after a proactive message

    def __init__(self, engine: ConversationEngine, fe: Frontend,
                 tick_normal: Optional[float] = None,
                 tick_cooldown: Optional[float] = None,
                 tick_asleep: Optional[float] = None,
                 tick_error: Optional[float] = None):
        self._engine = engine
        self._fe = fe
        # Tick lengths are instance-overridable primarily for tests.
        self._tick_normal = tick_normal if tick_normal is not None else self.TICK_NORMAL
        self._tick_cooldown = tick_cooldown if tick_cooldown is not None else self.TICK_COOLDOWN
        self._tick_asleep = tick_asleep if tick_asleep is not None else self.TICK_ASLEEP
        self._tick_error = tick_error if tick_error is not None else self.TICK_ERROR
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # F1: silent 退避冷却——next LLM decision earliest timestamp
        self._next_decision_after: float = 0.0

    # ── Main loop ──

    async def run(self) -> None:
        cooldown = 0
        sleep_cooldown = 0
        while not self._stop.is_set():
            try:
                engine = self._engine

                # Sleep/Wake cycle (checked only outside transition cooldown)
                if sleep_cooldown == 0:
                    should_sleep, msg = await engine.get_sleep_state()
                    if msg:
                        logger.info(f"[runtime] sleep/wake: sleeping={engine.is_sleeping} msg={msg[:50]}")
                        engine.touch()
                        cooldown = self.SLEEP_MSG_COOLDOWN_TICKS
                        sleep_cooldown = self.SLEEP_TRANSITION_TICKS
                        await self._emit(self._fe.on_proactive, msg)
                        engine.persist_proactive_message(msg, metadata={"sleep": True})
                        if should_sleep:
                            await engine.generate_dream()
                else:
                    sleep_cooldown = max(0, sleep_cooldown - 1)

                if engine.is_sleeping:
                    await asyncio.sleep(self._tick_asleep)
                    continue

                idle = engine.idle_seconds
                if idle < self.IDLE_FLOOR_SECONDS or cooldown > 0:
                    cooldown = max(0, cooldown - 1)
                    if idle < self.IDLE_FLOOR_SECONDS:
                        # F1: 用户活跃期间清除 silent 退避冷却与计数
                        self._next_decision_after = 0.0
                        engine.reset_silents()
                    await asyncio.sleep(self._tick_cooldown)
                    continue

                # F1: silent 退避冷却——冷却期内不触发 LLM 决策
                if time.time() < self._next_decision_after:
                    await asyncio.sleep(self._tick_cooldown)
                    continue

                score = engine.calculate_proactivity(idle)
                if random.random() < score:
                    intent = await self._run_blocking(engine.decide_proactive_action, idle)
                    # #177: LLM 主路径的话题同样记入去重队列，
                    # 与 fallback 的 pick_proactive_topic 行为对齐
                    if intent.topic_hint:
                        engine.record_topic(intent.topic_hint)
                    response = None
                    if intent.action == "explore" and engine.check_rate_limit("explore"):
                        response = await self._run_blocking(partial(engine.handle_explore, intent=intent))
                    elif intent.action == "chat" and engine.check_rate_limit("chat"):
                        response = await self._run_blocking(partial(engine.handle_proactive, intent=intent))
                    else:
                        if intent.action == "silent":
                            engine.record_silent()  # F1: 连续 silent 计数
                            cd = engine.silent_cooldown_seconds()
                            self._next_decision_after = time.time() + cd
                            logger.debug(f"[runtime] inner drive chose silent: {intent.reasoning[:80]}")
                            logger.info(f"[runtime] silent cooldown={cd:.0f}s")
                        else:
                            logger.debug(f"[runtime] rate limit blocked action={intent.action}")
                    if response:
                        engine.touch()
                        engine.record_rate_limit(intent.action)
                        engine.reset_silents()  # F1: 主动消息发出后重置退避
                        self._next_decision_after = 0.0
                        cooldown = self.PROACTIVE_COOLDOWN_TICKS
                        await self._emit(self._fe.on_proactive, response)

                await asyncio.sleep(self._tick_normal)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[runtime] tick error: {e}", exc_info=True)
                await asyncio.sleep(self._tick_error)

    # ── Hosting ──

    def start_in_thread(self) -> None:
        """Start the loop in a daemon thread with its own event loop (CLI)."""
        if self._thread is not None:
            return

        def _thread_main():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run())
            finally:
                loop.close()

        self._thread = threading.Thread(
            target=_thread_main, daemon=True, name="runtime-driver",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to end. Task cancellation (Web) also ends it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # ── Internals ──

    async def _run_blocking(self, fn, *args):
        """Run a blocking (LLM-calling) function in the default executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *args)

    @staticmethod
    async def _emit(callback, *args):
        """Call a frontend callback; await it when it is async (Web)."""
        result = callback(*args)
        if inspect.isawaitable(result):
            await result
