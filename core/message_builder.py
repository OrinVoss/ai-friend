"""Prompt message-array construction: history filters + budgets.

Extracted from core/message_handler.py (God Object 拆分，2026-07-22)。
Pure module function — no state of its own; everything comes from the agent.
"""

import logging

from core.context_manager import estimate_tokens

logger = logging.getLogger(__name__)


def build_messages(agent, sys_prompt: str, user_input: str | None) -> list[dict]:
    """Build the messages array for an LLM call: system prompt + filtered,
    budgeted history + optional current input.

    Filters (in order): current-input dedup, is_tool_claim, sleep turns,
    error_fallback turns, stage directions. Budgets: react_history_budget_chars
    (chars, 0=disable) then COMPRESS_THRESHOLD (tokens, triggers compression).
    """
    messages = [{"role": "system", "content": sys_prompt}]
    overflow = False
    # MH-007: accumulate a running token total and stop as soon as the
    # budget is exhausted.  Only messages that fit into the window are
    # reversed; this avoids a full-history scan on every request.
    running_total = 0
    history_messages = []
    is_first = True
    # T2: character-based history budget (overrides token budget for
    # typical Chinese text; set to 0 to disable).
    _budget = getattr(agent.config, 'react_history_budget_chars', 16000)
    react_budget = _budget if isinstance(_budget, int) else 0
    running_chars = 0
    dropped = 0
    for t in agent.short_term.get_all_reversed():
        # 修复：当前输入在 handle_message 时已 add_turn 入历史，末尾还会
        # 以"用户输入：..."形式再追加一次——跳过历史里的这份（即倒序首个
        # 元素），避免同一句话在 prompt 中出现两次（模型会误以为用户在刷屏）
        if is_first and user_input and t.role == "user" \
                and t.content.strip() and t.content.strip() in user_input:
            is_first = False
            continue
        is_first = False
        # #130: skip turns with stage directions / fake tool claims
        if getattr(t, 'metadata', None) and t.metadata.get('is_tool_claim'):
            continue
        # R4: skip sleep turns (zzzz, 我去午睡了, etc.) — 同 short_term.format_for_prompt 的过滤逻辑
        if getattr(t, 'metadata', None) and t.metadata.get('sleep'):
            continue
        # 修复：错误兜底文案（API 故障期的"抱歉，我暂时无法处理…"）不进
        # prompt 历史——保留在 DB/界面记录，但不让模型误以为发生过系统错误
        if getattr(t, 'metadata', None) and t.metadata.get('error_fallback'):
            continue
        if any(t.content.strip().startswith(p) for p in ['（调用', '(调用', '（前奏', '(前奏']):
            continue
        role = "assistant" if t.role == "assistant" else "user"
        # T2: char budget — drop oldest turns when total chars exceed budget
        turn_chars = len(t.content)
        if react_budget > 0 and running_chars + turn_chars > react_budget:
            dropped += 1
            break
        running_chars += turn_chars
        turn_tokens = estimate_tokens(t.content)
        if agent.should_compress(running_total + turn_tokens):
            overflow = True
            break
        running_total += turn_tokens
        history_messages.append({"role": role, "content": t.content})
    # #168: O(k) slice assignment instead of O(k²) insert(1, ...)
    messages[1:1] = reversed(history_messages)
    if dropped:
        logger.info(f"[msg] history budget: kept={len(history_messages)} dropped={dropped}")
    if overflow and agent.get_compressed_summary():
        messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {agent.get_compressed_summary()}"})
    if user_input:
        msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
        if agent.should_compress(msg_tokens + estimate_tokens(user_input)):
            agent.compress_context(messages)
        messages.append({"role": "user", "content": user_input})
    return messages
