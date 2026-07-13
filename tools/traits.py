import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# #258: canonical list of external tool names, shared across modules
EXTERNAL_TOOL_NAMES = [
    "web_fetch", "web_search", "read_file", "glob", "grep",
    "music_play", "notify",
]


@dataclass
class ToolResult:
    success: bool
    output: str

    @staticmethod
    def ok(output: str) -> "ToolResult":
        return ToolResult(success=True, output=output)

    @staticmethod
    def fail(error: str) -> "ToolResult":
        return ToolResult(success=False, output=error)

    def to_dict(self) -> dict:  # #273
        return {"success": self.success, "output": self.output}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


class Tool:
    """Base class for all tools. Subclass must define name(), description(), parameters_schema(), and execute()."""

    # #183: optional permission metadata — empty list means no restrictions
    required_permissions: list[str] = []

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
        Includes tool-specific properties to guide model output format. (#273)
        """
        tool_names = []
        for spec in self.list_specs():
            if names is not None and spec.name not in names:
                continue
            tool_names.append(spec.name)

        return {
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "calls": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "enum": tool_names if tool_names else ["web_fetch"],
                                    "description": "要调用的工具名称",
                                },
                                "arguments": {
                                    "type": "object",
                                    "description": "工具参数，根据具体工具而定",
                                },
                            },
                            "required": ["name", "arguments"],
                        },
                    },
                },
            },
        }