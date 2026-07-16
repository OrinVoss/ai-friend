"""Unified conversation engine (unified-pipeline P1).

Wraps the Agent's MessageHandler behind a single event-driven interface so
CLI and Web become two frontends over ONE pipeline instead of two separate
pipeline implementations. The engine owns no conversation state of its own
— the Agent remains the source of truth.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Frontend:
    """Base frontend: every callback is a no-op by default.

    Frontends (CLI terminal, Web WebSocket) subclass and override what they
    render. The engine only emits cleaned events — raw streams and tool
    markup never reach the frontend.
    """

    def on_token(self, token: str) -> None:
        """Streamed token of the current response (first generation pass)."""

    def on_message_done(self, text: str) -> None:
        """A complete reply is ready (fired whether or not it was streamed)."""

    def on_proactive(self, text: str) -> None:
        """The engine produced a proactive / explore message."""

    def on_sleep_reply(self, text: str) -> None:
        """A reply produced while the agent is sleeping."""

    def on_status(self, status: str) -> None:
        """Transient status hint (e.g. "正在搜索…")."""

    def on_error(self, error: str) -> None:
        """Pipeline error worth surfacing to the user."""


class ConversationEngine:
    """The single conversation pipeline shared by CLI and Web.

    Thin wrapper over Agent + MessageHandler: user input in, cleaned
    frontend events out. Owns no state — safe to construct per session.
    """

    def __init__(self, agent):
        self._agent = agent

    @property
    def a(self):
        return self._agent

    def handle_message(self, user_input: str, fe: Frontend) -> str:
        """Process one user message through the three-Agent pipeline.

        Emits on_token (streamed first pass), then exactly one of
        on_message_done / on_sleep_reply; on_error on failure.
        """
        a = self._agent
        try:
            was_sleeping = a._sleeping
            result = a._messages.handle_message(user_input, on_token=fe.on_token)
        except Exception as e:
            logger.exception("[engine] handle_message failed")
            fe.on_error(str(e))
            return ""
        if not result:
            return result
        if was_sleeping:
            fe.on_sleep_reply(result)
        else:
            fe.on_message_done(result)
        return result

    def handle_proactive(self, fe: Frontend, intent=None) -> Optional[str]:
        """Proactive chat turn. Emits on_proactive when a message is produced."""
        result = self._agent.process_proactive(on_token=fe.on_token, intent=intent)
        if result:
            fe.on_proactive(result)
        return result or None

    def handle_explore(self, fe: Frontend, intent=None) -> Optional[str]:
        """Free-explore turn. Silent stays silent — no event when unshared."""
        result = self._agent.process_explore(intent=intent)
        if result:
            fe.on_proactive(result)
        return result

    async def get_sleep_state(self) -> tuple[bool, str | None]:
        return await self._agent._get_sleep_state()

    def get_emotion_summary(self) -> dict:
        """Lightweight emotion snapshot for command/status layers."""
        e = self._agent.personality.emotion
        return {
            "dominant": e.dominant_emotion,
            "valence": e.valence,
            "arousal": e.arousal,
            "consecutive_negative": getattr(e, "consecutive_negative", 0),
        }

    def get_relationship(self) -> dict:
        return self._agent.ltm.get_relationship()
