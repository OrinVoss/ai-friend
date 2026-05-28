import json
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class KimiProvider:
    def __init__(self, endpoint: str, api_key: str, model: str,
                 temperature: float = 0.8, max_tokens: int = 2048,
                 thinking: Optional[str] = None,
                 reasoning_effort: Optional[str] = None,
                 timeout: int = 180):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def generate(self, messages: list[dict],
                 stream: bool = True,
                 on_token: Optional[callable] = None,
                 max_tokens: Optional[int] = None) -> str:
        chat_url = f"{self.endpoint}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        if self.thinking:
            payload["thinking"] = {"type": self.thinking}

        last_error = None
        for attempt in range(3):
            try:
                return self._do_request(chat_url, payload, stream, on_token)
            except requests.exceptions.ConnectionError as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"API connection error, retrying in {wait}s: {e}")
                time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                last_error = e
                if e.response.status_code < 500:
                    raise
                wait = 2 ** attempt
                logger.warning(f"API http error, retrying in {wait}s: {e}")
                time.sleep(wait)
            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.StreamConsumedError) as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"Stream error, retrying in {wait}s: {e}")
                time.sleep(wait)

        raise ConnectionError(f"API request failed after 3 retries: {last_error}")

    def _do_request(self, url: str, payload: dict, stream: bool,
                    on_token: Optional[callable]) -> str:
        resp = self.session.post(
            url,
            json=payload,
            stream=True,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        if not stream:
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

        full_response = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    o = json.loads(data_str)
                    choices = o.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "")
                    if token and on_token:
                        on_token(token)
                    full_response.append(token)
                except json.JSONDecodeError:
                    continue

        return "".join(full_response)
