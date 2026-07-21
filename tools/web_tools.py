"""Web search and fetch tools using AnySearch API."""
import ipaddress
import json
import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import requests

from tools.traits import (
    Tool, ToolResult,
    ERROR_TYPE_PARAM_ERROR, ERROR_TYPE_NETWORK_ERROR,
    ERROR_TYPE_NOT_FOUND, ERROR_TYPE_INTERNAL,
)

logger = logging.getLogger(__name__)

ANYSEARCH_ENDPOINT = "https://api.anysearch.com/mcp"

# #155: private/loopback IP ranges to block for SSRF prevention
_BLOCKED_CIDRS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# WT-001: module-level singleton session — reuse TCP connection + headers
# across calls instead of opening a new Session (and a new TCP handshake + TLS)
# every time _anysearch_api is called.
_HTTP_SESSION: requests.Session | None = None
_HTTP_SESSION_TS: float = 0.0
_SESSION_TTL = 300  # recycle once every 5 minutes to pick up env var changes


def _session() -> requests.Session:
    """Lazy-init, periodically-recycled HTTP session (WT-001)."""
    global _HTTP_SESSION, _HTTP_SESSION_TS
    now = time.time()
    if _HTTP_SESSION is None or (now - _HTTP_SESSION_TS) > _SESSION_TTL:
        if _HTTP_SESSION is not None:
            try:
                _HTTP_SESSION.close()
            except Exception:
                pass
        s = requests.Session()
        s.trust_env = False
        _HTTP_SESSION = s
        _HTTP_SESSION_TS = now
    return _HTTP_SESSION


def _is_safe_url(url: str) -> bool:
    """Check URL doesn't point to internal/private network. (#155)"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Block raw IPs to private ranges
        try:
            addr = ipaddress.ip_address(hostname)
            for cidr in _BLOCKED_CIDRS:
                if addr in cidr:
                    logger.warning(f"[web] blocked internal IP: {hostname}")
                    return False
        except ValueError:
            pass  # hostname, not IP — check below
        # Block localhost variants
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        return True
    except Exception:
        return False


# WT-004: valid freshness values
_VALID_FRESHNESS = {"day", "week", "month", "year"}


def _anysearch_api(tool_name: str, arguments: dict) -> dict:
    """Call AnySearch JSON-RPC 2.0 API with retry (WT-003) and nonce ID (WT-002)."""
    api_key = os.environ.get("ANYSEARCH_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,  # WT-002: non-fixed id
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    # WT-003: exponential backoff, up to 3 retries
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            session = _session()
            resp = session.post(ANYSEARCH_ENDPOINT, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if "error" in result:
                raise RuntimeError(result["error"].get("message", str(result["error"])))
            return result.get("result", {})
        except Exception as e:
            last_error = e
            logger.debug(f"[web] api call attempt {attempt+1} failed: {e}")
            if attempt < 3:
                time.sleep(2 ** attempt)  # 1, 2, 4s
    raise last_error or RuntimeError("unknown API error")


class WebSearchTool(Tool):
    """Search the web using AnySearch API."""

    # Layer5-WT1: network-heavy tool gets a longer leash.
    timeout_seconds = 45.0

    def name(self) -> str:
        return "web_search"

    def description(self) -> str:
        return (
            "搜索网络信息，获取实时资讯、新闻、百科知识。支持中文搜索。"
            "用于查找你不确定的最新信息、事实核查、资料查询。"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，支持自然语言",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条结果，默认 5",
                    "default": 5,
                },
                "freshness": {
                    "type": "string",
                    "description": "时效性：day/week/month/year，不填则不限制",
                    "enum": ["day", "week", "month", "year"],
                },
            },
            "required": ["query"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "").strip()
        max_results = min(int(args.get("max_results", 5)), 10)
        freshness = args.get("freshness", "").strip() or None

        if not query:
            return ToolResult.fail(
                "请提供搜索关键词",
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )

        # WT-004: validate freshness enum before passing to API
        if freshness is not None and freshness not in _VALID_FRESHNESS:
            logger.warning(f"[web] ignoring invalid freshness: {freshness}")
            freshness = None

        logger.info(f"[tool] web_search query={query[:60]} n={max_results} freshness={freshness}")
        try:
            arguments = {"query": query, "max_results": max_results}
            if freshness:
                arguments["freshness"] = freshness
            result = _anysearch_api("search", arguments)

            # AnySearch returns content as [{"type": "text", "text": "markdown..."}]
            content = result.get("content", [])
            if isinstance(content, str):
                return ToolResult.ok(f"搜索「{query}」结果：\n{content}")
            if isinstance(content, list) and content and "text" in content[0]:
                return ToolResult.ok(f"搜索「{query}」结果：\n{content[0]['text']}")

            return ToolResult.ok(f"未找到关于「{query}」的结果。")
        except Exception as e:
            logger.warning(f"Web search failed: {e}")
            return ToolResult.fail(
                f"搜索失败: {e}",
                error_type=ERROR_TYPE_NETWORK_ERROR,
                retryable=True,
            )


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using AnySearch extract API."""

    timeout_seconds = 45.0

    def name(self) -> str:
        return "web_fetch"

    def description(self) -> str:
        return "获取网页的完整文本内容。用于阅读URL指向的文章、文档、新闻等。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要获取的网页URL",
                },
            },
            "required": ["url"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        url = args.get("url", "").strip()

        if not url:
            return ToolResult.fail(
                "请提供URL",
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )

        # #241: proper URL validation — reject non-http schemes, fix protocol-relative URLs
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")):
            parsed = urlparse(url)
            if parsed.scheme and parsed.scheme not in ("http", "https"):
                return ToolResult.fail(
                    f"不支持的协议: {parsed.scheme}，仅支持 http/https",
                    error_type=ERROR_TYPE_PARAM_ERROR,
                    retryable=False,
                )
            url = "https://" + url

        # #155: SSRF prevention — block internal/private URLs
        if not _is_safe_url(url):
            return ToolResult.fail(
                f"出于安全原因，不能访问内网地址: {url}",
                error_type=ERROR_TYPE_PERMISSION_DENIED,
                retryable=False,
            )

        logger.info(f"[tool] web_fetch url={url[:80]}")
        try:
            result = _anysearch_api("extract", {"url": url})
            content = result.get("content", "") or result.get("text", "")

            if not content:
                return ToolResult.fail(
                    f"未能提取网页内容: {url}",
                    error_type=ERROR_TYPE_NOT_FOUND,
                    retryable=False,
                )

            title = result.get("title", "")
            header = f"网页 {url}" + (f"\n标题: {title}" if title else "")
            return ToolResult.ok(f"{header}:\n```\n{content[:8000]}\n```")
        except Exception as e:
            logger.warning(f"Web fetch failed: {e}")
            return ToolResult.fail(
                f"获取网页失败: {e}",
                error_type=ERROR_TYPE_NETWORK_ERROR,
                retryable=True,
            )
