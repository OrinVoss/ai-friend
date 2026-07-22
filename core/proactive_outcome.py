"""Proactive-outcome attribution (L4-6a): link proactive messages to care
entries and score the user's reply.

Extracted from core/message_handler.py (God Object 拆分，2026-07-22)。
Module functions take the agent explicitly; MessageHandler keeps thin delegates.
"""

import logging
import time

logger = logging.getLogger(__name__)


def match_active_care(agent, topic: str, reasoning: str) -> dict | None:
    """L4-6a: find the active inner-drive entry that the proactive topic
    likely surfaced. Returns a lightweight dict or None."""
    state = getattr(agent, "_inner_drive_state", None)
    if state is None:
        return None
    query = f"{topic} {reasoning}".strip()
    try:
        if query:
            hits = state.surface_for_query(query)
            if hits:
                return {"entry_id": hits[0].id, "timestamp": time.time()}
    except Exception as e:
        logger.debug(f"[msg] proactive care surface failed: {e}")
    try:
        for e in state.active_entries():
            if e.content and (e.content in topic or e.content in reasoning):
                return {"entry_id": e.id, "timestamp": time.time()}
    except Exception as e:
        logger.debug(f"[msg] proactive care substring match failed: {e}")
    return None


def evaluate_proactive_outcome(agent, entry: dict, user_input: str) -> None:
    """L4-6a: score the user's reply to the last proactive message and
    record the outcome on the matched care entry."""
    state = getattr(agent, "_inner_drive_state", None)
    if state is None:
        return
    entry_id = entry.get("entry_id")
    try:
        sentiment, _, _ = agent.consolidator.analyze_sentiment(user_input)
        positive = sentiment > 0.1
        state.record_outcome(entry_id, positive)
        logger.info(f"[msg] proactive outcome recorded: entry={entry_id} positive={positive}")
    except Exception as e:
        logger.warning(f"[msg] proactive outcome evaluation failed: {e}")
