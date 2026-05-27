import json
from dataclasses import dataclass, field
from typing import Any, Optional


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


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


class Tool:
    """Base class for all tools. Subclass must define name(), description(), parameters_schema(), and execute()."""

    def name(self) -> str:
        raise NotImplementedError

    def description(self) -> str:
        raise NotImplementedError

    def parameters_schema(self) -> dict:
        raise NotImplementedError

    async def execute(self, args: dict[str, Any]) -> ToolResult:
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

    def format_for_prompt(self) -> str:
        """Render tools as markdown for system prompt injection."""
        parts = []
        for spec in self.list_specs():
            params_str = json.dumps(spec.parameters, indent=2, ensure_ascii=False)
            parts.append(
                f"- **{spec.name}**: {spec.description}\n"
                f"  参数: {params_str}"
            )
        return "\n\n".join(parts) if parts else "(无可用工具)"
