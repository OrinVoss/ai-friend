"""Tests for core/runtime_driver.py — shared sleep/proactivity loop (P2)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.conversation_engine import Frontend
from core.runtime_driver import RuntimeDriver


class RecordingFrontend(Frontend):
    def __init__(self):
        self.events = []

    def on_proactive(self, text): self.events.append(("proactive", text))
    def on_error(self, error): self.events.append(("error", error))


class AsyncRecordingFrontend(Frontend):
    """Web-style frontend: async callbacks the driver must await."""

    def __init__(self):
        self.events = []

    async def on_proactive(self, text): self.events.append(("proactive", text))


def _intent(action, reasoning="因为想你"):
    return MagicMock(action=action, reasoning=reasoning, topic_hint=None)


def _engine(**overrides):
    e = MagicMock()
    e.get_sleep_state = AsyncMock(return_value=(False, None))
    e.generate_dream = AsyncMock(return_value="梦")
    e.is_sleeping = False
    e.idle_seconds = 100.0
    e.calculate_proactivity.return_value = 1.0  # always fire
    e.decide_proactive_action.return_value = _intent("chat")
    e.check_rate_limit.return_value = True
    e.handle_proactive.return_value = "主动消息"
    e.handle_explore.return_value = "探索分享"
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


def _run_driver(engine, fe, ticks=0.15):
    """Run the driver briefly, then stop it; return the event list."""
    async def _main():
        driver = RuntimeDriver(engine, fe, tick_normal=0.01,
                               tick_cooldown=0.01, tick_asleep=0.01,
                               tick_error=0.01)
        task = asyncio.create_task(driver.run())
        await asyncio.sleep(ticks)
        driver.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(_main())


class TestRuntimeDriver(unittest.TestCase):
    def test_proactive_chat_emits_event(self):
        fe = RecordingFrontend()
        engine = _engine()
        _run_driver(engine, fe)

        self.assertIn(("proactive", "主动消息"), fe.events)
        engine.record_rate_limit.assert_called_with("chat")
        engine.touch.assert_called()

    def test_explore_emits_event(self):
        fe = RecordingFrontend()
        engine = _engine(decide_proactive_action=MagicMock(
            return_value=_intent("explore")))
        _run_driver(engine, fe)

        self.assertIn(("proactive", "探索分享"), fe.events)
        engine.record_rate_limit.assert_called_with("explore")

    def test_silent_intent_no_event(self):
        fe = RecordingFrontend()
        engine = _engine(decide_proactive_action=MagicMock(
            return_value=_intent("silent", "用户似乎在忙")))
        _run_driver(engine, fe)

        self.assertEqual(fe.events, [])
        engine.handle_proactive.assert_not_called()
        engine.handle_explore.assert_not_called()

    def test_rate_limit_blocks_action(self):
        fe = RecordingFrontend()
        engine = _engine(check_rate_limit=MagicMock(return_value=False))
        _run_driver(engine, fe)

        self.assertEqual(fe.events, [])
        engine.handle_proactive.assert_not_called()

    def test_sleep_transition_emits_persists_dreams(self):
        fe = RecordingFrontend()
        engine = _engine(
            get_sleep_state=AsyncMock(return_value=(True, "困了去睡了…")),
            is_sleeping=True,
        )
        _run_driver(engine, fe)

        self.assertIn(("proactive", "困了去睡了…"), fe.events)
        engine.persist_proactive_message.assert_called_with(
            "困了去睡了…", metadata={"sleep": True})
        engine.generate_dream.assert_awaited()

    def test_sleeping_skips_proactivity(self):
        fe = RecordingFrontend()
        engine = _engine(is_sleeping=True)  # asleep, no transition message
        _run_driver(engine, fe)

        self.assertEqual(fe.events, [])
        engine.decide_proactive_action.assert_not_called()

    def test_idle_below_floor_skips_proactivity(self):
        fe = RecordingFrontend()
        engine = _engine(idle_seconds=5.0)
        _run_driver(engine, fe)

        self.assertEqual(fe.events, [])
        engine.decide_proactive_action.assert_not_called()

    def test_async_frontend_callback_awaited(self):
        fe = AsyncRecordingFrontend()
        engine = _engine()
        _run_driver(engine, fe)

        self.assertIn(("proactive", "主动消息"), fe.events)

    def test_stop_ends_loop(self):
        engine = _engine()
        driver = RuntimeDriver(engine, RecordingFrontend(),
                               tick_normal=0.01, tick_cooldown=0.01)

        async def _main():
            task = asyncio.create_task(driver.run())
            await asyncio.sleep(0.05)
            driver.stop()
            await asyncio.wait_for(task, timeout=2)
            return task

        task = asyncio.run(_main())
        self.assertTrue(task.done())


if __name__ == "__main__":
    unittest.main()
