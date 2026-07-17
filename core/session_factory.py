"""Shared session assembly for CLI and Web (unified-pipeline P0).

Both frontends used to hand-wire the same stack (repo → ltm → retriever →
consolidator → tools → agent) in two places — `main.py` and
`web/session.py` — and the two copies had already drifted (tool set,
rerank fn, monitor sources). This module is the single wiring point:
db / provider / embed engine stay process-shared; everything else is built
per session — including the Repository, so concurrent sessions can no
longer race on a shared `repo.session_id` (web.md P0).
"""
import logging
from dataclasses import dataclass
from typing import Optional

from config import Config
from core.agent import Agent
from core.personality import Personality
from core.provider import LLMProvider, DeepSeekProvider
from memory.consolidation import MemoryConsolidator
from memory.embeddings import EmbeddingEngine
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.short_term import ConversationBuffer
from storage.database import Database
from storage.repository import Repository
from tools.traits import ToolRegistry
from tools.memory_tools import RecallTool, RememberTool
from tools.file_tools import ReadFileTool, FileTreeTool
from tools.notify_tool import NotifyTool
from tools.web_tools import WebSearchTool, WebFetchTool
from tools.music_tool import MusicPlayTool
from tools.search_tools import GlobTool, GrepTool
from ui.cli import ConsoleInterface

logger = logging.getLogger(__name__)


def build_provider(config: Config) -> DeepSeekProvider:
    """Process-shared LLM provider (single construction site)."""
    return DeepSeekProvider(
        endpoint=config.api_endpoint,
        api_key=config.api_key,
        model=config.api_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        thinking=config.thinking,
        reasoning_effort=config.reasoning_effort,
        timeout=config.api_timeout,
        monitor_enabled=getattr(config, "monitor_enabled", True),
    )


def build_embed_engine(config: Config) -> EmbeddingEngine:
    """Process-shared embedding engine (single construction site)."""
    return EmbeddingEngine(
        endpoint=config.embedding_endpoint,
        dim=config.embedding_dim,
    )


def make_embedding_sampler(repo: Repository):
    """Sampler for the startup embedding self-check: returns one stored
    embedding BLOB, from any session (vectors are content-derived)."""
    def _sample():
        from core.async_utils import run_async

        async def _q():
            async with repo.db.cursor() as c:
                await c.execute(
                    "SELECT embedding FROM user_facts "
                    "WHERE embedding IS NOT NULL LIMIT 1")
                row = await c.fetchone()
                return row["embedding"] if row else None
        return run_async(_q())
    return _sample


@dataclass
class SessionBundle:
    """Per-session objects produced by assemble_session()."""
    repo: Repository
    ltm: LongTermMemory
    short_term: ConversationBuffer
    retriever: MemoryRetriever
    consolidator: MemoryConsolidator
    tool_registry: ToolRegistry
    agent: Agent


def assemble_session(config: Config, db: Database, session_id: str,
                     personality: Personality, provider: LLMProvider,
                     embed_engine: Optional[EmbeddingEngine] = None,
                     ui: Optional[ConsoleInterface] = None,
                     include_file_tree: bool = False,
                     enable_llm_rerank: bool = False) -> SessionBundle:
    """Wire one full session stack.

    Behavior-preserving extraction of the former `main.py` /
    `web/session.py` WebAgent assembly. Two historical frontend
    differences are kept as explicit parameters until they are resolved
    deliberately (P0 = no behavior change):

    - `include_file_tree`: CLI registers FileTreeTool, Web does not.
    - `enable_llm_rerank`: CLI passes an LLM rerank fn to the retriever,
      Web does not.
    """
    repo = Repository(db)
    repo.session_id = session_id
    ltm = LongTermMemory(repo)
    short_term = ConversationBuffer(maxlen=config.short_term_capacity)

    def llm_generate(prompt: str, temperature: float = 0.2) -> str:
        return provider.generate([{"role": "user", "content": prompt}],
                                 stream=False, source="consolidation")

    llm_rerank_fn = None
    if enable_llm_rerank:
        def _rerank(prompt: str) -> str:
            return provider.generate([{"role": "user", "content": prompt}],
                                     stream=False, source="rerank")
        llm_rerank_fn = _rerank

    retriever = MemoryRetriever(ltm, llm_rerank_fn=llm_rerank_fn,
                                embedding_engine=embed_engine)
    consolidator = MemoryConsolidator(ltm, llm_generate,
                                      embedding_engine=embed_engine,
                                      config=config)

    tool_registry = ToolRegistry()
    tool_registry.register(RecallTool(retriever, ltm))
    tool_registry.register(RememberTool(ltm))
    tool_registry.register(ReadFileTool())
    if include_file_tree:
        tool_registry.register(FileTreeTool())
    tool_registry.register(NotifyTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(WebFetchTool())
    tool_registry.register(MusicPlayTool())
    tool_registry.register(GlobTool())
    tool_registry.register(GrepTool())

    agent = Agent(
        personality=personality, provider=provider, ltm=ltm,
        retriever=retriever, consolidator=consolidator,
        short_term=short_term, ui=ui, config=config,
        session_id=session_id,
    )
    agent._tool_registry = tool_registry

    logger.debug(f"[factory] session assembled: {session_id} "
                 f"({len(tool_registry.list_specs())} tools)")
    return SessionBundle(
        repo=repo, ltm=ltm, short_term=short_term, retriever=retriever,
        consolidator=consolidator, tool_registry=tool_registry, agent=agent,
    )
