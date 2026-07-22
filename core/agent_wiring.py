"""Lazy assembly of the three-Agent pipeline's collaborators.

Extracted from core/message_handler.py (God Object 拆分，2026-07-22)。
Holds the lazy singletons (InnerDrive / ToolAgent / MemoryAgent / internal
registries) so MessageHandler only orchestrates.
"""

import logging

logger = logging.getLogger(__name__)


class AgentWiring:
    """Lazy-builds and caches the pipeline's collaborator objects."""

    def __init__(self, agent, prompt_cache):
        self.agent = agent
        self.prompt_cache = prompt_cache
        self._inner_drive = None
        self._memory_agent = None
        self._tool_agent = None
        self._internal_registry = None
        self._internal_registry_full = None

    # ── Agent 1 ──

    def ensure_inner_drive(self):
        if self._inner_drive is None:
            from core.inner_drive import InnerDriveAgent
            a = self.agent
            # #203: create isolated registry for Agent 1 (recall/remember only)
            isolated = self.make_internal_registry()
            cfg = a.config
            # MA-001: inject MemoryAgent only when the gray switch is on
            memory_agent = None
            if getattr(cfg, "use_memory_agent", False):
                memory_agent = self.ensure_memory_agent()
                logger.info("[msg] inner drive: memory agent enabled (use_memory_agent)")
            # Proactive think loop: persistent care list (per-session file).
            # Prefer the shared instance from session_factory (also wired to
            # the consolidator); fall back to creating one here.
            inner_drive_state = getattr(a, "_inner_drive_state", None)
            if inner_drive_state is None and getattr(cfg, "proactive_think_loop", True):
                from core.inner_drive_state import InnerDriveState
                inner_drive_state = InnerDriveState(
                    session_id=getattr(a, "session_id", None) or "default",
                    max_entries=getattr(cfg, "inner_drive_care_list_size", 20),
                    embedding_engine=getattr(a.consolidator, "_embed", None),
                    surface_top_k=getattr(cfg, "inner_drive_surface_top_k", 8),
                    response_top_k=getattr(cfg, "inner_drive_surface_response_k", 3),
                    decay_rate=getattr(cfg, "inner_drive_decay_rate", 0.9),
                    similarity_threshold=getattr(
                        cfg, "inner_drive_care_similarity_threshold", 0.7),
                )
            self._inner_drive = InnerDriveAgent(
                provider=a.provider,
                personality=a.personality,
                ltm=a.ltm,
                retriever=a.retriever,
                short_term=a.short_term,
                tool_registry=isolated,
                tool_call_history=a.tool_call_history,
                session_id=getattr(a, "session_id", None),
                prompt_cache=self.prompt_cache,
                prompt_cache_ttl=getattr(cfg, "prompt_cache_ttl_seconds", 60.0),
                memory_agent=memory_agent,
                # M-06: prompt 的工具规则/检查清单用全量 registry 生成，
                # Agent 1 判断 needs_external_tools 需要看到外部工具
                rule_tools_registry=a.tool_registry,
                proactive_think_loop=getattr(cfg, "proactive_think_loop", True),
                proactive_think_max_rounds=getattr(cfg, "proactive_think_max_rounds", 2),
                inner_drive_state=inner_drive_state,
            )

    # ── MemoryAgent ──

    def ensure_memory_agent(self):
        """Lazily build the MemoryAgent for InnerDrive injection (MA-001)."""
        if self._memory_agent is None:
            from memory.memory_agent import MemoryAgent
            from memory.lifecycle import MemoryLifecycleManager
            a = self.agent
            embed = getattr(a.consolidator, "_embed", None)
            lifecycle = MemoryLifecycleManager(
                a.ltm, config=a.config, embedding_engine=embed)
            # P2: 指代解析用的 LLM 与对话历史（缺一则内部回退规则路径）
            def _clues_llm(prompt: str) -> str:
                return a.provider.generate(
                    [{"role": "user", "content": prompt}],
                    stream=False, max_tokens=128, source="memory_clues")
            self._memory_agent = MemoryAgent(
                a.ltm, lifecycle, a.retriever, embedding_engine=embed,
                relevance_floor=getattr(a.config, "memory_agent_relevance_floor", 0.35),
                relevance_full=getattr(a.config, "memory_agent_relevance_full", 0.75),
                coreference_threshold=getattr(a.config, "memory_agent_coreference_threshold", 0.78),  # R2
                llm_fn=_clues_llm,
                history_fn=lambda: a.short_term.format_for_prompt(max_tokens=800),
                inner_drive_state=getattr(a, "_inner_drive_state", None),
            )
        return self._memory_agent

    # ── Agent 2 ──

    def ensure_tool_agent(self):
        if self._tool_agent is None:
            from core.tool_agent import ToolAgent
            self._tool_agent = ToolAgent(
                provider=self.agent.provider,
                tool_registry=self.make_external_registry(),
            )

    # ── Registries ──

    def make_internal_registry(self, include_history_search: bool = False):
        """Isolated registry (recall/remember) for Agent 1 / Agent 3.

        H-01: cached and reused — RecallTool/RememberTool 无可变内部状态，
        重复新建没有收益。
        include_history_search: 仅 Agent 3 需要 history_search（按需找回被
        历史预算裁剪的原始对话）；Agent 1 有 recall 循环已够用，不带它可让
        Agent 1 prompt 少 ~660 chars 工具 schema（T1 瘦身成果不被吃回）。
        """
        key = "_internal_registry_full" if include_history_search else "_internal_registry"
        if getattr(self, key) is None:
            from tools.traits import ToolRegistry
            from tools.memory_tools import RecallTool, RememberTool, HistorySearchTool
            a = self.agent
            r = ToolRegistry()
            if a.retriever is not None and a.ltm is not None:
                r.register(RecallTool(retriever=a.retriever, ltm=a.ltm))
                r.register(RememberTool(ltm=a.ltm))
                if include_history_search:
                    r.register(HistorySearchTool(retriever=a.retriever, ltm=a.ltm))
            setattr(self, key, r)
        return getattr(self, key)

    def make_external_registry(self):
        """Build a registry containing only external tools for Agent 2."""
        from tools.traits import ToolRegistry, EXTERNAL_TOOL_NAMES
        r = ToolRegistry()
        for name in EXTERNAL_TOOL_NAMES:
            tool = self.agent.tool_registry.get(name)
            if tool and not getattr(tool, "is_internal", False):
                r.register(tool)
        return r
