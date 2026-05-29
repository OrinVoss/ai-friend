#!/usr/bin/env python3
"""AI Friend — 一个有记忆和人格的 AI 朋友控制台应用。"""

import logging
import sys

from config import load_config
from core.agent import Agent
from core.personality import Personality
from core.provider import KimiProvider
from memory.short_term import ConversationBuffer
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.consolidation import MemoryConsolidator
from storage.database import Database
from storage.repository import Repository
from tools.traits import ToolRegistry
from tools.memory_tools import RecallTool, RememberTool
from tools.file_tools import ReadFileTool
from tools.notify_tool import NotifyTool
from tools.web_tools import WebSearchTool, WebFetchTool
from tools.music_tool import MusicPlayTool
from tools.search_tools import GlobTool, GrepTool
from ui.cli import ConsoleInterface


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main():
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    # Initialize storage
    db = Database(config.db_path)
    repo = Repository(db)

    # Initialize personality
    personality = Personality.load(config.personality_file)
    logger.info(f"Loaded personality: {personality.config.name}")

    # Initialize memory systems
    ltm = LongTermMemory(repo)
    short_term = ConversationBuffer(maxlen=config.short_term_capacity)

    # Initialize provider
    provider = KimiProvider(
        endpoint=config.api_endpoint,
        api_key=config.api_key,
        model=config.api_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        thinking=config.thinking,
        reasoning_effort=config.reasoning_effort,
        timeout=config.api_timeout,
    )

    # Wrap LLM for single-turn structured calls
    def llm_generate(prompt: str, temperature: float = 0.2) -> str:
        messages = [{"role": "user", "content": prompt}]
        return provider.generate(messages, stream=False)

    # Wrap LLM for reranking (single-turn, returns short text)
    def llm_rerank(prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        return provider.generate(messages, stream=False)

    # Initialize memory components
    retriever = MemoryRetriever(ltm, llm_rerank_fn=llm_rerank)
    consolidator = MemoryConsolidator(ltm, llm_generate)

    # Initialize UI
    ui = ConsoleInterface()

    # Initialize tools
    tool_registry = ToolRegistry()
    tool_registry.register(RecallTool(retriever, ltm))
    tool_registry.register(RememberTool(ltm))
    tool_registry.register(ReadFileTool())
    tool_registry.register(NotifyTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(WebFetchTool())
    tool_registry.register(MusicPlayTool())
    tool_registry.register(GlobTool())
    tool_registry.register(GrepTool())
    logger.info(f"Registered {len(tool_registry.list_specs())} tools")

    # Initialize agent
    agent = Agent(
        personality=personality,
        provider=provider,
        ltm=ltm,
        retriever=retriever,
        consolidator=consolidator,
        short_term=short_term,
        ui=ui,
        config=config,
    )
    agent._tool_registry = tool_registry

    try:
        agent.run()
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    main()
