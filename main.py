#!/usr/bin/env python3
"""AI Friend — 一个有记忆和人格的 AI 朋友控制台应用。"""

import asyncio
import logging
import sys

from config import load_config
from core.agent import Agent
from core.embedding_server import auto_start_embedding
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


async def main():
    try:
        config = load_config()
        setup_logging(config.log_level)
        logger = logging.getLogger(__name__)
        logger.info(f"Starting AI Friend CLI: model={config.api_model} personality={config.personality_file} log_level={config.log_level}")
        auto_start_embedding(logger)

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

        # Initialize UI — CL-001: pass typing_speed from config so the display
        # engine actually uses the user-configured value instead of the default 0.02.
        ui = ConsoleInterface(typing_speed=config.typing_speed)

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
        except Exception as e:
            logger.exception(f"Unhandled error in main loop: {e}")
        finally:
            # MA-005: close must be awaited
            await db.close()
    except Exception as e:
        # MA-001: initialization error — print friendly message instead of cryptic traceback
        logger.critical(f"Failed to start: {e}")
        print(f"\n[错误] 启动失败: {e}")
        print("请检查 config.json 配置是否正确，或查看日志文件获取详细信息。")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
