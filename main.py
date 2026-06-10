#!/usr/bin/env python3
"""AI Friend — 一个有记忆和人格的 AI 朋友控制台应用。"""

import asyncio
import logging
import os
import subprocess
import time

from config import load_config
from core.agent import Agent
from core.personality import Personality
from core.provider import KimiProvider
from core.logging_setup import setup_logging
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


def _auto_start_embedding(logger, endpoint="http://localhost:8080/v1/embeddings"):
    """Start embedding server if not running. Non-blocking after launch."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(endpoint, timeout=2)
        resp.read()
        logger.info("[embed] server already running")
        return
    except Exception:
        pass

    project = os.path.dirname(os.path.abspath(__file__))
    llama_server = os.path.join(project, "memory", "llama-bin", "llama-server.exe")
    model = os.path.join(project, "memory", "Qwen3.5-0.8B-Q6_K.gguf")
    if not os.path.exists(llama_server) or not os.path.exists(model):
        logger.info("[embed] binary or model not found, skipping auto-start")
        return

    logger.info("[embed] starting embedding server...")
    try:
        subprocess.Popen(
            [llama_server, "-m", model, "--embeddings", "--port", "8080",
             "-ngl", "99", "--ctx-size", "2048", "--batch-size", "512",
             "--threads", "4", "--host", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for i in range(10):
            time.sleep(1)
            try:
                resp = urllib.request.urlopen(endpoint, timeout=1)
                resp.read()
                logger.info(f"[embed] server ready ({i+1}s)")
                return
            except Exception:
                continue
        logger.warning("[embed] server did not respond within 10s, falling back to keyword search")
    except Exception as e:
        logger.warning(f"[embed] failed to start: {e}")


async def main():
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting AI Friend CLI: model={config.api_model} personality={config.personality_file} log_level={config.log_level}")
    _auto_start_embedding(logger)

    # Initialize storage
    db = Database(config.db_path)
    await db.open()
    repo = Repository(db)

    # Initialize personality
    personality = Personality.load(config.personality_file)

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

    # Initialize local embedding engine (optional, graceful degradation)
    from memory.embeddings import EmbeddingEngine
    embed_engine = EmbeddingEngine(
        endpoint=config.embedding_endpoint,
        dim=config.embedding_dim,
    )

    # Initialize memory components
    retriever = MemoryRetriever(ltm, llm_rerank_fn=llm_rerank,
                                embedding_engine=embed_engine)
    consolidator = MemoryConsolidator(ltm, llm_generate,
                                      embedding_engine=embed_engine)

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
    asyncio.run(main())
