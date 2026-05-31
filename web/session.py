import uuid
import logging
from threading import Lock
from typing import Optional

from config import Config
from core.personality import Personality
from core.provider import KimiProvider
from core.agent import Agent
from memory.short_term import ConversationBuffer
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.consolidation import MemoryConsolidator
from tools.traits import ToolRegistry
from tools.memory_tools import RecallTool, RememberTool
from tools.file_tools import ReadFileTool
from tools.notify_tool import NotifyTool
from tools.web_tools import WebSearchTool, WebFetchTool
from tools.music_tool import MusicPlayTool
from tools.search_tools import GlobTool, GrepTool
from storage.database import Database
from storage.repository import Repository

logger = logging.getLogger(__name__)


class WebAgent:
    def __init__(self, config: Config, db: Database, repo: Repository):
        self.config = config
        self.db = db
        self.repo = repo
        self.personality = Personality.load(config.personality_file)
        self.ltm = LongTermMemory(repo)
        self.short_term = ConversationBuffer(maxlen=config.short_term_capacity)
        # Restore recent conversation from DB (fixes #98)
        for t in repo.get_recent_turns(30):
            self.short_term.add_turn(t["role"], t["content"])
        self._on_token_callback = None

        self.provider = KimiProvider(
            endpoint=config.api_endpoint, api_key=config.api_key,
            model=config.api_model, temperature=config.temperature,
            max_tokens=config.max_tokens,
            thinking=config.thinking, reasoning_effort=config.reasoning_effort,
            timeout=config.api_timeout,
        )

        def llm_gen(prompt, temperature=0.2):
            return self.provider.generate([{"role": "user", "content": prompt}], stream=False)

        from memory.embeddings import EmbeddingEngine
        embed_engine = EmbeddingEngine(
            endpoint=config.embedding_endpoint,
            dim=config.embedding_dim,
        )

        self.retriever = MemoryRetriever(self.ltm, embedding_engine=embed_engine)
        self.consolidator = MemoryConsolidator(self.ltm, llm_gen,
                                                embedding_engine=embed_engine)

        registry = ToolRegistry()
        registry.register(RecallTool(self.retriever, self.ltm))
        registry.register(RememberTool(self.ltm))
        registry.register(ReadFileTool())
        registry.register(NotifyTool())
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        registry.register(MusicPlayTool())
        registry.register(GlobTool())
        registry.register(GrepTool())
        self.tool_registry = registry

        self.agent = Agent(
            personality=self.personality, provider=self.provider,
            ltm=self.ltm, retriever=self.retriever,
            consolidator=self.consolidator, short_term=self.short_term,
            config=config,
        )
        self.agent._tool_registry = registry

    def set_on_token(self, callback):
        self._on_token_callback = callback

    def process_message(self, user_input: str) -> str:
        result = self.agent.process_message(
            user_input, on_token=self._on_token_callback,
        )
        self.personality.save(self.config.personality_file)
        return result

    def process_proactive(self) -> str:
        result = self.agent.process_proactive(
            on_token=self._on_token_callback,
        )
        self.personality.save(self.config.personality_file)
        return result

    def process_explore(self) -> str | None:
        result = self.agent.process_explore()
        self.personality.save(self.config.personality_file)
        return result

    @property
    def emotion(self):
        return self.personality.emotion.dominant_emotion

    @property
    def turn_count(self):
        return self.agent.turn_count


class SessionManager:
    def __init__(self, config: Config):
        self.config = config
        self.db: Database | None = None
        self.repo: Repository | None = None
        self._sessions: dict[str, WebAgent] = {}
        self._lock = Lock()

    async def open(self):
        self.db = Database(self.config.db_path)
        await self.db.open()
        self.repo = Repository(self.db)

    def get_or_create(self, session_id: Optional[str] = None) -> tuple[str, WebAgent]:
        with self._lock:
            sid = session_id or uuid.uuid4().hex[:12]
            if sid not in self._sessions:
                logger.info(f"[session] create: {sid}")
                self._sessions[sid] = WebAgent(self.config, self.db, self.repo)
            else:
                logger.debug(f"[session] restore: {sid}")
            return sid, self._sessions[sid]

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            logger.info(f"Session removed: {session_id}")

    def cleanup_old(self, max_sessions: int = 50) -> None:
        with self._lock:
            while len(self._sessions) > max_sessions:
                oldest = next(iter(self._sessions))
                self._sessions.pop(oldest)
                logger.info(f"Session evicted: {oldest}")
