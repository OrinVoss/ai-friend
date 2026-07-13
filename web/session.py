import time
import uuid
import logging
import os
import shutil
from threading import Lock
from typing import Optional

from config import Config
from core.async_utils import run_async
from core.personality import Personality
from core.provider import LLMProvider, DeepSeekProvider
from core.agent import Agent
from memory.short_term import ConversationBuffer
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.consolidation import MemoryConsolidator
from memory.embeddings import EmbeddingEngine
from models.personality import PersonalityConfig
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
    def __init__(self, config: Config, db: Database, repo: Repository,
                 session_id: str = "default",
                 role_id: Optional[str] = None,
                 shared_provider: Optional[LLMProvider] = None,
                 shared_embed_engine: Optional[EmbeddingEngine] = None):
        self.config = config
        self.db = db
        self.repo = repo
        self.session_id = session_id
        repo.session_id = session_id  # #40
        self.role_id = role_id or "default"
        self.personality_path = self._ensure_personality_file(self.role_id)
        self.personality = Personality.load(self.personality_path)
        self.ltm = LongTermMemory(repo)
        self.short_term = ConversationBuffer(maxlen=config.short_term_capacity)
        # Restore recent conversation from DB (fixes #98)
        for t in repo.get_recent_turns_sync(30):
            self.short_term.add_turn(t["role"], t["content"])
        self._on_token_callback = None

        # SN-005/006: reuse the SessionManager-shared Provider/EmbeddingEngine
        # instead of constructing a fresh HTTP session per tab. Each tab still
        # gets its own Agent/personality, but the underlying HTTP pool is shared.
        if shared_provider is not None:
            self.provider = shared_provider
        else:
            self.provider = DeepSeekProvider(
                endpoint=config.api_endpoint, api_key=config.api_key,
                model=config.api_model, temperature=config.temperature,
                max_tokens=config.max_tokens,
                thinking=config.thinking, reasoning_effort=config.reasoning_effort,
                timeout=config.api_timeout,
            )

        def llm_gen(prompt, temperature=0.2):
            return self.provider.generate([{"role": "user", "content": prompt}], stream=False)

        if shared_embed_engine is not None:
            embed_engine = shared_embed_engine
        else:
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
            config=config, session_id=self.session_id,
        )
        self.agent._tool_registry = registry
        # Restore turn counter so page refreshes don't reset it (#RS-001)
        try:
            max_turn = run_async(self.repo.get_max_turn_number())
            self.agent.turn_count = max_turn
        except Exception as e:
            logger.warning(f"[session] restore turn_count failed: {e}")
        self._last_save_time: float = 0.0  # #44: debounce personality save
        self._ensure_relationship_defaults()

    def _save_personality_debounced(self) -> None:
        """Save personality at most once every 30s to reduce disk writes. (#44)"""
        now = time.time()
        if now - getattr(self, '_last_save_time', 0.0) < 30:
            return
        self._last_save_time = now
        try:
            self.personality.save(self.personality_path)
        except Exception as e:
            logger.warning(f"[session] save personality failed: {e}")

    def close(self) -> None:
        """SN-013: release per-session resources on eviction/shutdown.

        Only personality (a plain JSON file handle) is per-session; the shared
        Provider/EmbeddingEngine sessions are owned by SessionManager and closed
        there. Save personality one last time so no emotion delta is lost.
        """
        try:
            self.personality.save(self.personality_path)
        except Exception as e:
            logger.warning(f"[session] close save personality failed: {e}")

    def _ensure_personality_file(self, role_id: str) -> str:
        """Return the path to the role-specific personality file, copying the
        configured template if the role file does not yet exist."""
        os.makedirs("personalities", exist_ok=True)
        path = os.path.join("personalities", f"{role_id}.json")
        if not os.path.exists(path):
            template = self.config.personality_file
            if os.path.exists(template):
                shutil.copy(template, path)
                logger.info(f"[session] copied personality template {template} -> {path}")
            else:
                Personality(PersonalityConfig()).save(path)
                logger.info(f"[session] created default personality at {path}")
        return path

    def _ensure_relationship_defaults(self) -> None:
        """Seed relationship metric rows for this session if missing."""
        try:
            run_async(self.repo.ensure_relationship_defaults())
        except Exception as e:
            logger.warning(f"[session] ensure relationship defaults failed: {e}")

    def set_on_token(self, callback):
        self._on_token_callback = callback

    def process_message(self, user_input: str) -> str:
        result = self.agent.process_message(
            user_input, on_token=self._on_token_callback,
        )
        self._save_personality_debounced()
        return result

    def process_proactive(self, on_token=None, *, intent=None) -> str:
        result = self.agent.process_proactive(
            on_token=on_token or self._on_token_callback,
            intent=intent,
        )
        self._save_personality_debounced()
        return result

    def process_explore(self, intent=None) -> str | None:
        result = self.agent.process_explore(intent=intent)
        self._save_personality_debounced()
        return result

    def process_proactive_with_intent(self, intent) -> str:
        """Convenience for run_in_executor (no keyword args)."""
        return self.process_proactive(intent=intent)

    def process_explore_with_intent(self, intent) -> str | None:
        """Convenience for run_in_executor (no keyword args)."""
        return self.process_explore(intent=intent)

    @property
    def emotion(self):
        return self.personality.emotion.dominant_emotion

    @property
    def turn_count(self):
        return self.agent.turn_count

    @property
    def last_activity(self):
        return self.agent.last_activity_time

    @last_activity.setter
    def last_activity(self, value):
        self.agent.last_activity_time = value

    @property
    def last_activity_time(self):
        return self.agent.last_activity_time

    @last_activity_time.setter
    def last_activity_time(self, value):
        self.agent.last_activity_time = value

    @property
    def is_sleeping(self):
        return self.agent._sleeping

    async def get_sleep_state(self):
        return await self.agent._get_sleep_state()

    async def generate_dream(self):
        return await self.agent._generate_dream()

    def calculate_proactivity(self, idle_duration: float) -> float:
        return self.agent._calculate_proactivity(idle_duration)

    def check_rate_limit(self, action: str) -> bool:
        return self.agent.check_rate_limit(action)

    def record_rate_limit(self, action: str) -> None:
        self.agent.record_rate_limit(action)

    def decide_proactive_action(self, idle_duration: float):
        return self.agent.decide_proactive_action(idle_duration)

    def save_personality(self) -> None:
        """Persist personality state to disk."""
        try:
            self.personality.save(self.personality_path)
        except Exception as e:
            logger.warning(f"[session] save personality failed: {e}")


class SessionManager:
    def __init__(self, config: Config):
        self.config = config
        self.db: Database | None = None
        self.repo: Repository | None = None
        self._sessions: dict[str, WebAgent] = {}
        self._proactive_tasks: dict[str, object] = {}  # sid → asyncio.Task
        self._active_ws: dict[str, object] = {}  # sid → WebSocket
        self._lock = Lock()
        # SN-005/006: shared HTTP sessions for Provider + EmbeddingEngine —
        # every WebAgent reuses these so we don't open one requests.Session
        # (and one EmbeddingCache) per open tab.
        self._shared_provider: LLMProvider | None = None
        self._shared_embed_engine: EmbeddingEngine | None = None
        self._create_count: int = 0  # #123: throttle cleanup_old

    async def open(self):
        self.db = Database(self.config.db_path)
        await self.db.open()
        self.repo = Repository(self.db)
        # SN-005/006: build the shared clients once for all future sessions.
        self._shared_provider = DeepSeekProvider(
            endpoint=self.config.api_endpoint, api_key=self.config.api_key,
            model=self.config.api_model, temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            thinking=self.config.thinking, reasoning_effort=self.config.reasoning_effort,
            timeout=self.config.api_timeout,
        )
        self._shared_embed_engine = EmbeddingEngine(
            endpoint=self.config.embedding_endpoint,
            dim=self.config.embedding_dim,
        )

    def get_or_create(self, session_id: Optional[str] = None,
                      role_id: Optional[str] = None) -> tuple[str, WebAgent]:
        with self._lock:
            # 一个角色只有一个 session：session_id 与 role_id 保持一致
            if role_id:
                sid = role_id
            elif session_id:
                sid = session_id
            else:
                sid = "default"

            if sid in self._sessions:
                logger.debug(f"[session] restore: {sid}")
                return sid, self._sessions[sid]

            # Restore role mapping for an existing DB session when caller
            # did not supply a role_id.
            if role_id is None:
                try:
                    mapped = run_async(self.repo.get_role_for_session(sid))
                    if mapped:
                        role_id = mapped
                except Exception as e:
                    logger.warning(f"[session] get_role_for_session failed: {e}")
            role_id = role_id or "default"

            logger.info(f"[session] create: {sid} role={role_id}")
            agent = WebAgent(
                self.config, self.db, self.repo, session_id=sid, role_id=role_id,
                shared_provider=self._shared_provider,
                shared_embed_engine=self._shared_embed_engine,
            )
            self._sessions[sid] = agent
            try:
                run_async(self.repo.set_session_role(sid, agent.role_id))
            except Exception as e:
                logger.warning(f"[session] set_session_role failed: {e}")
            # #123: trigger cleanup every 10 new sessions to evict stale REST sessions
            self._create_count += 1
            if self._create_count % 10 == 0:
                self.cleanup_old()
            return sid, agent

    def remove(self, session_id: str) -> None:
        with self._lock:
            agent = self._sessions.pop(session_id, None)
            # SN-013: release per-session resources before dropping the ref.
            if agent is not None:
                try:
                    agent.close()
                except Exception as e:
                    logger.warning(f"[session] close on remove failed: {e}")
            task = self._proactive_tasks.pop(session_id, None)
            if task:
                task.cancel()
            self._active_ws.pop(session_id, None)
            logger.info(f"Session removed: {session_id}")

    def register_proactive(self, session_id: str, task, websocket) -> None:
        """Register or replace proactive task for a session. Cancels old task if exists."""
        with self._lock:
            old_task = self._proactive_tasks.pop(session_id, None)
            if old_task:
                old_task.cancel()
            self._proactive_tasks[session_id] = task
            self._active_ws[session_id] = websocket
            logger.info(f"[session] proactive registered: {session_id}")

    def get_active_ws(self, session_id: str):
        """Get the currently active WebSocket for a session."""
        return self._active_ws.get(session_id)

    def cleanup_old(self, max_sessions: int = 50, ttl_seconds: int = 86400) -> None:
        """Remove idle sessions beyond max or TTL. (#148: 24h TTL; SN-016 wire-up)"""
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, agent in self._sessions.items()
                if now - agent.last_activity > ttl_seconds
            ]
            for sid in expired:
                agent = self._sessions.pop(sid, None)
                if agent is not None:
                    try:
                        agent.close()
                    except Exception as e:
                        logger.warning(f"[session] close on TTL failed: {e}")
                task = self._proactive_tasks.pop(sid, None)
                if task:
                    task.cancel()
                self._active_ws.pop(sid, None)
                logger.info(f"Session expired (TTL): {sid}")
            while len(self._sessions) > max_sessions:
                oldest = next(iter(self._sessions))
                agent = self._sessions.pop(oldest, None)
                if agent is not None:
                    try:
                        agent.close()
                    except Exception as e:
                        logger.warning(f"[session] close on evict failed: {e}")
                task = self._proactive_tasks.pop(oldest, None)
                if task:
                    task.cancel()
                self._active_ws.pop(oldest, None)
                logger.info(f"Session evicted: {oldest}")

    async def shutdown(self) -> None:
        """Graceful shutdown: save all sessions, cancel tasks. (#212)"""
        logger.info("Shutting down sessions...")
        for sid, agent in list(self._sessions.items()):
            try:
                agent.save_personality()
            except Exception as e:
                logger.warning(f"Failed to save personality for {sid}: {e}")
        # SN-013: also close each WebAgent so per-session resources release.
        for sid, agent in list(self._sessions.items()):
            try:
                agent.close()
            except Exception as e:
                logger.warning(f"[session] close on shutdown failed: {e}")
        self._sessions.clear()
        for task in self._proactive_tasks.values():
            task.cancel()
        self._proactive_tasks.clear()
        self._active_ws.clear()
        # SN-005/006: close the shared HTTP sessions once at shutdown.
        if self._shared_provider is not None:
            try:
                self._shared_provider.session.close()
            except Exception as e:
                logger.warning(f"[session] close shared provider failed: {e}")
            self._shared_provider = None
        if self._shared_embed_engine is not None:
            try:
                self._shared_embed_engine._session.close()
            except Exception as e:
                logger.warning(f"[session] close shared embed engine failed: {e}")
            self._shared_embed_engine = None
        # #27: close database connection
        if self.db is not None:
            try:
                await self.db.close()
            except Exception as e:
                logger.warning(f"[session] close db failed: {e}")
