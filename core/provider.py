"""LLM API provider — kimi/deepseek-compatible chat completions."""
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

from core.monitor import record_call

# PR-013: cap streamed response at 1 MB to prevent unbounded memory growth
STREAM_MAX_BYTES = 1_048_576  # 1 MiB


class TruncatedResponseError(Exception):
    """A2（2026-07-21，provider.md P0-1）：response_format 调用发生截断——
    半截 JSON 对下游等同于格式错误，视为可重试错误（与网络错误同级）。"""


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Defines the minimal interface expected by Agent, InnerDrive, and memory
    components. Concrete providers must implement :meth:`generate`.
    """

    @abstractmethod
    def generate(self, messages: list[dict],
                 stream: bool = True,
                 on_token: Optional[callable] = None,
                 max_tokens: Optional[int] = None,
                 response_format: Optional[dict] = None,
                 source: str = "",
                 temperature: Optional[float] = None) -> str:
        """Generate a text completion from the LLM.

        Args:
            messages: OpenAI-style chat messages.
            stream: Whether to stream tokens.
            on_token: Optional callback invoked for each streamed token.
            max_tokens: Optional override for the default output token limit.
            response_format: Optional JSON schema / response_format dict.
            source: Optional caller label for the monitor (e.g. "react", "tool_agent").
            temperature: Optional per-call override; None uses the instance default.

        Returns:
            The full generated text.
        """
        ...


class DeepSeekProvider(LLMProvider):
    # F6: circuit breaker — class-level counter shared across instances
    # (single provider, so instance-level is fine too)
    _circuit_failures: int = 0
    _circuit_open_until: float = 0.0

    def __init__(self, endpoint: str, api_key: str, model: str,
                 temperature: float = 0.8, max_tokens: int = 512,
                 thinking: Optional[str] = None,
                 reasoning_effort: Optional[str] = None,
                 timeout: int = 180,
                 monitor_enabled: bool = True,
                 stream_max_bytes: int = STREAM_MAX_BYTES):
        self.endpoint = endpoint.rstrip("/")
        # #261: endpoint 以 /v1 结尾时剥掉，避免拼出 /v1/v1/chat/completions
        if self.endpoint.endswith("/v1"):
            self.endpoint = self.endpoint[:-3]
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens   # PR-001: default aligned with config
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.monitor_enabled = monitor_enabled
        self.stream_max_bytes = stream_max_bytes
        # MN-002: apply monitor switch at provider level
        from core.monitor import set_monitor_enabled
        set_monitor_enabled(monitor_enabled)
        self.session = requests.Session()
        self.session.trust_env = False
        # PR-002: connection pool with limited size
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def generate(self, messages: list[dict],
                 stream: bool = True,
                 on_token: Optional[callable] = None,
                 max_tokens: Optional[int] = None,
                 response_format: Optional[dict] = None,
                 source: str = "",
                 temperature: Optional[float] = None) -> str:
        chat_url = f"{self.endpoint}/v1/chat/completions"

        # F6: circuit breaker — 连续 3 次完全失败后 60 秒内跳过 HTTP
        if self._circuit_open_until > time.time():
            logger.warning(f"[api] circuit breaker open ({self._circuit_open_until - time.time():.0f}s remaining), "
                          f"skipping request")
            raise ConnectionError(f"Circuit breaker open, last error: {getattr(self, '_circuit_last_error', 'unknown')}")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            # 按调用覆盖温度（决策类任务用低温，角色扮演保持实例默认 0.8）
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        if response_format:
            payload["response_format"] = response_format

        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        if self.thinking:
            payload["thinking"] = {"type": self.thinking}

        last_error = None
        for attempt in range(3):
            try:
                t0 = time.monotonic()
                resp_text, meta = self._do_request(chat_url, payload, stream, on_token)
                # A2: response_format 调用截断 → 半截 JSON 等同可重试错误
                if meta["truncated"] and response_format:
                    raise TruncatedResponseError(
                        f"response truncated ({meta['truncation_reason']})")
                if meta["truncated"]:
                    # 纯文本聊天路径保持现状（半截回复好于报错），仅记录
                    logger.warning(f"[api] response truncated: {meta['truncation_reason']} "
                                   f"(returning partial)")
                elapsed = (time.monotonic() - t0) * 1000
                # MN-001: record every successful API call to the monitor buffer
                record_call(
                    model=self.model,
                    messages=messages,
                    response=resp_text,
                    duration_ms=elapsed,
                    max_tokens=max_tokens or self.max_tokens,
                    # 与实际发送的 payload 温度一致（可能被按调用覆盖）
                    temperature=temperature if temperature is not None else self.temperature,
                    response_format=response_format,
                    source=source,
                    truncated=meta["truncated"],
                    finish_reason=meta["finish_reason"],
                )
                # F6: circuit breaker — 成功时重置
                self._circuit_failures = 0
                self._circuit_open_until = 0.0
                return resp_text
            except TruncatedResponseError as e:
                last_error = e
                wait = min(2 ** attempt * 2, 15)
                logger.warning(f"[api] truncated attempt={attempt+1}/3 retry_in={wait}s: {e}")
                time.sleep(wait)
            except requests.exceptions.ConnectionError as e:
                last_error = e
                wait = min(2 ** attempt * 2, 15)  # F6: 2/4/8s (原 1/2/4s)
                logger.warning(f"[api] connection error attempt={attempt+1}/3 retry_in={wait}s: {e}")
                time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                last_error = e
                if e.response.status_code < 500:
                    # PR-004: parse Retry-After header for 429
                    if e.response.status_code == 429:
                        retry_after = e.response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                wait = int(retry_after)
                            except ValueError:
                                wait = 60
                            logger.warning(f"[api] rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                            time.sleep(wait)
                            continue
                    raise
                wait = min(2 ** attempt * 2, 15)  # F6: 2/4/8s (原 1/2/4s)
                logger.warning(f"[api] http error attempt={attempt+1}/3 retry_in={wait}s: {e}")
                time.sleep(wait)
            # #213: ReadTimeout 纳入重试；StreamConsumedError 在本路径不可达（死 catch），移除
            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ReadTimeout) as e:
                last_error = e
                wait = min(2 ** attempt * 2, 15)  # F6: 2/4/8s (原 1/2/4s)
                logger.warning(f"[api] stream error attempt={attempt+1}/3 retry_in={wait}s: {e}")
                time.sleep(wait)

        # F6: circuit breaker — 每次完全失败累加，连续 3 次后 60 秒跳过 HTTP
        self._circuit_failures += 1
        if self._circuit_failures >= 3:
            self._circuit_open_until = time.time() + 60.0
            self._circuit_last_error = str(last_error)
            logger.warning(f"[api] circuit breaker tripped ({self._circuit_failures} consecutive failures, "
                          f"open for 60s)")
        else:
            self._circuit_open_until = 0.0
        logger.error(f"[api] failed after 3 retries: {last_error}")
        raise ConnectionError(f"API request failed after 3 retries: {last_error}")

    def _do_request(self, url: str, payload: dict, stream: bool,
                    on_token: Optional[callable]) -> tuple[str, dict]:
        """返回 (content, meta)。meta: truncated/finish_reason/truncation_reason
        ——A2：截断显式化，不再静默当成功。"""
        meta = {"truncated": False, "finish_reason": "", "truncation_reason": ""}
        t0 = time.monotonic()  # PR-006
        input_chars = sum(len(m.get("content", "")) for m in payload.get("messages", []))

        resp = self.session.post(
            url,
            json=payload,
            stream=True,
            timeout=(10, self.timeout),  # #174: connect=10s, read=self.timeout
        )
        # #213: try/finally 保证提前 break / 异常时也能 close 响应，连接归还连接池
        try:
            resp.raise_for_status()

            if not stream:
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                finish_reason = choice.get("finish_reason", "") or ""
                meta["finish_reason"] = finish_reason
                if finish_reason == "length":
                    meta["truncated"] = True
                    meta["truncation_reason"] = "finish_reason=length"
                usage = data.get("usage", {})
                elapsed = time.monotonic() - t0  # PR-006
                logger.info(
                    f"[api] model={self.model} stream=off "
                    f"tok_in={usage.get('prompt_tokens', '?')} tok_out={usage.get('completion_tokens', '?')} "
                    f"duration={elapsed:.2f}s chars_in={input_chars} chars_out={len(content)}"
                )
                return content, meta

            full_response = []
            stream_size = 0  # PR-013: accumulated bytes
            saw_done = False  # A2: 缺 [DONE] 也视为截断（断流）
            stream_deadline = time.monotonic() + self.timeout  # PR-006
            for line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > stream_deadline:  # PR-006
                    logger.warning(f"[api] stream timeout after {self.timeout}s")
                    meta["truncated"] = True
                    meta["truncation_reason"] = "stream_timeout"
                    break
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        saw_done = True
                        break
                    try:
                        o = json.loads(data_str)
                        choices = o.get("choices", [])
                        if not choices:
                            continue
                        if choices[0].get("finish_reason"):
                            meta["finish_reason"] = choices[0]["finish_reason"]
                        delta = choices[0].get("delta", {})
                        token = delta.get("content") or ""
                        if token and on_token:
                            on_token(token)
                        full_response.append(token)
                        stream_size += len(token.encode("utf-8"))
                        if stream_size > self.stream_max_bytes:
                            logger.warning(f"[api] stream exceeded {self.stream_max_bytes} bytes, truncating")
                            meta["truncated"] = True
                            meta["truncation_reason"] = "stream_max_bytes"
                            break
                    except json.JSONDecodeError:
                        continue

            if not saw_done and not meta["truncated"]:
                meta["truncated"] = True
                meta["truncation_reason"] = "missing_done"

            content = "".join(full_response)
            elapsed = time.monotonic() - t0  # PR-006
            logger.info(
                f"[api] model={self.model} stream=on "
                f"duration={elapsed:.2f}s chars_in={input_chars} chars_out={len(content)}"
            )
            return content, meta
        finally:
            resp.close()
