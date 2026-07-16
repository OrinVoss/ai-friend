#!/usr/bin/env python3
"""AI Friend — 一个有记忆和人格的 AI 朋友控制台应用。"""

import asyncio
import logging
import sys

from config import load_config
from core.embedding_server import auto_start_embedding
from core.personality import Personality
from core.logging_setup import setup_logging
from core.session_factory import assemble_session, build_embed_engine, build_provider
from storage.database import Database
from ui.cli import ConsoleInterface


async def main():
    try:
        config = load_config()
        setup_logging(config.log_level)
        logger = logging.getLogger(__name__)
        logger.info(f"Starting AI Friend CLI: model={config.api_model} personality={config.personality_file} log_level={config.log_level}")
        auto_start_embedding(logger)

        # Initialize storage
        db = Database(config.db_path, backup_enabled=config.db_backup_enabled,
                      backup_keep=config.db_backup_keep)
        await db.open()

        # Initialize personality
        personality = Personality.load(config.personality_file)

        # Unified session assembly (unified-pipeline P0): provider and
        # embedding engine are process-shared, the rest is per session.
        provider = build_provider(config)
        embed_engine = build_embed_engine(config)

        # Initialize UI — CL-001: pass typing_speed from config so the display
        # engine actually uses the user-configured value instead of the default 0.02.
        ui = ConsoleInterface(typing_speed=config.typing_speed)

        bundle = assemble_session(
            config, db, session_id="default", personality=personality,
            provider=provider, embed_engine=embed_engine, ui=ui,
            include_file_tree=True, enable_llm_rerank=True,
        )
        agent = bundle.agent
        logger.info(f"Registered {len(bundle.tool_registry.list_specs())} tools")

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
