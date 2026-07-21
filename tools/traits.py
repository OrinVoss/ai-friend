import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# #258: canonical list of external tool names, shared across modules
EXTERNAL_TOOL_NAMES = [
    "web_fetch", "web_search", "read_file", "file_tree", "glob", "grep",
    "music_play", "notify",
]

# Tool error taxonomy. These values travel back to the LLM so it can decide
# whether to fix parameters, retry, or give up.
ERROR_TYPE_PARAM_ERROR = "param_error"
ERROR_TYPE_NOT_FOUND = "not_found"
ERROR_TYPE_NETWORK_ERROR = "network_error"
ERROR_TYPE_PERMISSION_DENIED = "permission_denied"
ERROR_TYPE_RATE_LIMITED = "rate_limited"
ERROR_TYPE_INTERNAL = "internal"

# Human-readable retry guidance keyed by error_type.
ERROR_TYPE_GUIDANCE = {
    ERROR_TYPE_PARAM_ERROR: "参数错误：请检查必填参数和类型后重试。",
    ERROR_TYPE_NOT_FOUND: "未找到：目标不存在，换来源或放弃。",
    ERROR_TYPE_NETWORK_ERROR: "网络错误：可能是临时故障，可以稍后重试。",
    ERROR_TYPE_PERMISSION_DENIED: "权限不足：无法访问该资源，请放弃。",
    ERROR_TYPE_RATE_LIMITED: "速率限制：请降低请求频率后重试。",
    ERROR_TYPE_INTERNAL: "内部错误：工具执行失败，请换方式或放弃。",
}


@dataclass
class ToolResult:
    success: bool
    output: str
    error_type: str = ""        # param_error / not_found / network_error /
                                # permission_denied / rate_limited / internal
    retryable: bool = False     # 这个错误值不值得重试
    elapsed_ms: float = 0.0

    @staticmethod
    def ok(output: str, elapsed_ms: float = 0.0) -> "ToolResult":
        return ToolResult(success=True, output=output, elapsed_ms=elapsed_ms)

    @staticmethod
    def fail(
        error: str,
        error_type: str = ERROR_TYPE_INTERNAL,
        retryable: bool = False,
        elapsed_ms: float = 0.0,
    ) -> "ToolResult":
        return ToolResult(
            success=False,
            output=error,
            error_type=error_type,
            retryable=retryable,
            elapsed_ms=elapsed_ms,
        )

    def to_dict(self) -> dict:  # #273
        return {
            "success": self.success,
            "output": self.output,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    def guidance(self) -> str:
        """Return a concise Chinese guidance string for the LLM."""
        if self.success:
            return ""
        base = ERROR_TYPE_GUIDANCE.get(self.error_type, self.output)
        if base != self.output and self.output:
            return f"{base} 详情：{self.output}"
        return base


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


class Tool:
    """Base class for all tools. Subclass must define name(), description(), parameters_schema(), and execute()."""

    # #183: optional permission metadata — empty list means no restrictions
    required_permissions: list[str] = []

    # Layer5-T1: default per-tool timeout. Network-heavy tools should override.
    timeout_seconds: float = 30.0

    # Layer5-T1: internal tools (recall/remember) are never exposed to Agent 2.
    is_internal: bool = False

    # KI-1: 参数别名表（原 dispatcher 全局别名下沉到各工具）。
    # 格式：{规范参数名: (别名1, 别名2, ...)}；规范名已存在时别名不生效。
    ALIASES: dict[str, tuple[str, ...]] = {}

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """KI-1: 把 LLM 给出的别名参数归一到本工具的规范参数名。

        dispatcher 只负责解析与分发，不再做全局参数改名——全局别名曾把
        notify 的 title 吃掉（title→song 冲突），各工具自己声明自己的别名。
        """
        if not self.ALIASES or not isinstance(args, dict):
            return args
        result = dict(args)
        for canonical, aliases in self.ALIASES.items():
            if canonical in result:
                continue
            for alias in aliases:
                if alias in result:
                    result[canonical] = result.pop(alias)
                    break
        return result

    def name(self) -> str:
        raise NotImplementedError

    def description(self) -> str:
        raise NotImplementedError

    def parameters_schema(self) -> dict:
        raise NotImplementedError

    def execute(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name(),
            description=self.description(),
            parameters=self.parameters_schema(),
        )


class ToolRegistry:
    """Registry of tools that LLM can call via <tool_call> tags."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name()] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def list_external_specs(self) -> list[ToolSpec]:
        """Return specs for non-internal tools only."""
        return [t.spec() for t in self._tools.values() if not getattr(t, "is_internal", False)]

    def format_for_prompt(self, names: list[str] | None = None) -> str:
        """Render tools as markdown for system prompt injection.

        Args:
            names: Optional list of tool names to include. If None, all tools.
        """
        parts = []
        for spec in self.list_specs():
            if names is not None and spec.name not in names:
                continue
            params_str = json.dumps(spec.parameters, indent=2, ensure_ascii=False)
            parts.append(
                f"- **{spec.name}**: {spec.description}\n"
                f"  参数: {params_str}"
            )
        return "\n\n".join(parts) if parts else "(无可用工具)"

    # #183: permission check — simple role-based access
    def check_permission(self, name: str, user_role: str = "user") -> bool:
        """Check if a user role has permission to call a tool."""
        tool = self._tools.get(name)
        if not tool:
            return False
        if not tool.required_permissions:
            return True
        allowed = user_role in tool.required_permissions
        if not allowed:
            logger.warning(
                f"[tool] permission denied: {name} required={tool.required_permissions} role={user_role}"
            )
        return allowed

    def to_json_schema(self, names: list[str] | None = None) -> dict:
        """Generate JSON Schema for structured tool call output.

        Returns schema compatible with DeepSeek response_format={"type": "json_object"}.
        Each tool contributes one calls-item variant: its name as a single-value
        enum plus its own parameters_schema() as the arguments schema. (#273)
        """
        variants = []
        for spec in self.list_specs():
            if names is not None and spec.name not in names:
                continue
            variants.append({
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": [spec.name],
                        "description": "要调用的工具名称",
                    },
                    "arguments": spec.parameters,
                },
                "required": ["name", "arguments"],
            })

        return {
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "calls": {
                        "type": "array",
                        # #273: 无工具时回退为泛 object（不再硬编码 web_fetch）
                        "items": {"oneOf": variants} if variants else {"type": "object"},
                    },
                },
                "required": ["calls"],
            },
        }
