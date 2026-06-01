"""Web search and fetch tools using AnySearch API."""
import ipaddress
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import requests

from tools.traits import Tool, ToolResult

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


def _anysearch_api(tool_name: str, arguments: dict) -> dict:
    """Call AnySearch JSON-RPC 2.0 API."""
    api_key = os.environ.get("ANYSEARCH_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    session = requests.Session()
    session.trust_env = False
    resp = session.post(ANYSEARCH_ENDPOINT, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if "error" in result:
        raise RuntimeError(result["error"].get("message", str(result["error"])))
    return result.get("result", {})


class WebSearchTool(Tool):
    """Search the web using AnySearch API."""

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
            return ToolResult.fail("请提供搜索关键词")

        logger.info(f"[tool] web_search query={query[:60]} n={max_results}")
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
            return ToolResult.fail(f"搜索失败: {e}")


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using AnySearch extract API."""

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
            return ToolResult.fail("请提供URL")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # #155: SSRF prevention — block internal/private URLs
        if not _is_safe_url(url):
            return ToolResult.fail(f"出于安全原因，不能访问内网地址: {url}")

        logger.info(f"[tool] web_fetch url={url[:80]}")
        try:
            result = _anysearch_api("extract", {"url": url})
            content = result.get("content", "") or result.get("text", "")

            if not content:
                return ToolResult.fail(f"未能提取网页内容: {url}")

            title = result.get("title", "")
            header = f"网页 {url}" + (f"\n标题: {title}" if title else "")
            return ToolResult.ok(f"{header}:\n```\n{content[:8000]}\n```")
        except Exception as e:
            logger.warning(f"Web fetch failed: {e}")
            return ToolResult.fail(f"获取网页失败: {e}")
