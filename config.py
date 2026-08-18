"""Configuration loader — dataclass + JSON file + env var overrides + validation."""
import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _validate(cfg: "Config") -> None:
    """CF-002: field-level validation — clamp out-of-range values on load."""
    messages = []
    if not 0.0 <= cfg.temperature <= 2.0:
        messages.append(f"temperature {cfg.temperature} out of [0,2], clamped to 0.8")
        cfg.temperature = 0.8
    if not 0 < cfg.api_timeout <= 600:
        messages.append(f"api_timeout {cfg.api_timeout} out of [1,600], clamped to 180")
        cfg.api_timeout = 180
    if not 0 < cfg.max_tokens <= 32768:
        messages.append(f"max_tokens {cfg.max_tokens} out of [1,32768], clamped to 512")
        cfg.max_tokens = 512
    if not 0 < cfg.embedding_dim <= 4096:
        messages.append(f"embedding_dim {cfg.embedding_dim} out of [1,4096], clamped to 1024")
        cfg.embedding_dim = 1024
    if cfg.api_key == "" and "DEEPSEEK_API_KEY" not in os.environ:
        messages.append("DEEPSEEK_API_KEY not set — LLM calls will fail")
    if cfg.prompt_cache_ttl_seconds < 0:
        messages.append(f"prompt_cache_ttl_seconds {cfg.prompt_cache_ttl_seconds} < 0, clamped to 60")
        cfg.prompt_cache_ttl_seconds = 60
    if cfg.conversation_examples_max_turns < 0:
        messages.append(f"conversation_examples_max_turns {cfg.conversation_examples_max_turns} < 0, clamped to 3")
        cfg.conversation_examples_max_turns = 3
    if cfg.degrade_threshold < 1:
        messages.append(f"degrade_threshold {cfg.degrade_threshold} < 1, clamped to 3")
        cfg.degrade_threshold = 3
    if cfg.max_fake_actions < 0:
        messages.append(f"max_fake_actions {cfg.max_fake_actions} < 0, clamped to 3")
        cfg.max_fake_actions = 3
    if cfg.agent2_total_timeout_seconds < 1:
        messages.append(f"agent2_total_timeout_seconds {cfg.agent2_total_timeout_seconds} < 1, clamped to 120")
        cfg.agent2_total_timeout_seconds = 120
    for msg in messages:
        logger.warning(f"[config] validation: {msg}")


@dataclass
class Config:
    api_endpoint: str = "https://api.deepseek.com"
    api_key: str = ""  # can be overridden by DEEPSEEK_API_KEY env var
    api_model: str = "deepseek-v4-flash"
    api_timeout: int = 180
    thinking: str = "disabled"
    reasoning_effort: str = ""
    personality_file: str = "personalities/default.json"
    db_path: str = "data/ai_friend.db"
    short_term_capacity: int = 500
    consolidation_interval: int = 5
    proactive_min_idle: float = 180.0
    proactive_max_interval: float = 600.0
    typing_speed: float = 0.005
    temperature: float = 0.8
    max_tokens: int = 512
    max_facts: int = 200
    max_experiences: int = 100
    max_reflections: int = 50
    max_tool_iterations: int = 5  # #152: ReAct loop max tool call iterations
    degrade_threshold: int = 3    # #255: consecutive tool failures before degrading
    max_fake_actions: int = 3     # #255: max fake action corrections
    agent2_total_timeout_seconds: int = 120  # L4-2: hard deadline for Agent 2 tool loop
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    # A1（2026-07-21）：Web 访问 token。空 = 不启用（行为与现状一致）。
    # 启用后：/api/* 需 Authorization: Bearer <token> 或 ?token=<token>，
    # WS init 消息需带 token 字段（web.md 一期）。
    web_access_token: str = ""
    log_level: str = "INFO"
    # CLI 交互期间的控制台日志级别（默认 WARNING——聊天界面只留警告/错误，
    # 完整日志始终写 logs/YYYY-MM-DD.log）；Web 模式不受影响
    console_log_level: str = "WARNING"
    # MN-003: LLM monitor switch -- disable in production to avoid leaking prompts
    monitor_enabled: bool = True
    allowed_read_paths: list[str] = field(default_factory=lambda: [
        ".",
        # CF-006: no hardcoded Windows paths — users set these in config.json
        "~/Documents",
        "~/Downloads",
    ])
    # Local embedding engine
    embedding_endpoint: str = "http://localhost:8080/v1/embeddings"
    embedding_dim: int = 1024
    embedding_cache_size: int = 1000
    # PC-001: hierarchical prompt cache settings (#160)
    prompt_cache_ttl_seconds: int = 60
    conversation_examples_max_turns: int = 3
    # MA-001: Memory Agent gray switch — InnerDrive uses memory_agent.answer()
    # for memory instead of retriever.retrieve_for_query() (memory-agent.md 7.1)
    use_memory_agent: bool = False
    # MA-002: Memory Agent relevance floor — measurable evidences below this
    # cosine similarity are dropped; confidence scales by top_sim/relevance_full
    memory_agent_relevance_floor: float = 0.35
    memory_agent_relevance_full: float = 0.75
    memory_agent_coreference_threshold: float = 0.78  # R2: 指代改写阈值（原 0.65 太松）
    # Proactive think loop (proactive-think-loop.md): bounded reflection loop
    # on the proactive path; False = legacy single-shot decision
    proactive_think_loop: bool = True
    proactive_think_max_rounds: int = 2  # F2: 默认 2 轮（原 3 轮，沉默期首轮即 silent 无需第 3 轮）
    inner_drive_care_list_size: int = 20
    # 内驱状态二期（inner-drive-state.md）：浮现规则与语义阈值
    inner_drive_surface_top_k: int = 8        # 独处时每轮思考浮现条数
    inner_drive_surface_response_k: int = 3   # 对话时相关浮现条数
    inner_drive_decay_rate: float = 0.9       # 浮现未行动的 priority 衰减率
    # A6（2026-07-21）：情绪按真实时间衰减——「一轮」对应的真实秒数
    emotion_turn_seconds: int = 300
    inner_drive_care_similarity_threshold: float = 0.7  # 语义浮现/对照解决阈值
    # A3: Agent 3 (react) 对话历史字符预算。历史消息总字符超过此值时，
    # 从最旧开始丢弃。设为 0 表示不限（默认 16000 ≈ 8-10k tokens）。
    react_history_budget_chars: int = 16000
    # Layer5-D1: dispatcher 格式化工具结果时的单条输出截断上限（字符）。
    # 影响 Agent 2 返回给 Agent 3 的工具结果长度。
    dispatcher_output_cap: int = 2000
    # PR-013: 流式响应安全上限（字节），防止无界内存增长。
    stream_max_bytes: int = 1_048_576  # 1 MiB
    # DB backup: VACUUM INTO snapshot before schema migrations (P0-3)
    db_backup_enabled: bool = True
    db_backup_keep: int = 5
    # CE-001: configurable conversation style examples (#28)
    conversation_examples: list[dict] = field(default_factory=lambda: [
        {
            "user": "今天去外滩拍照了，日落的时候光影特别好",
            "replies": [
                "蛙趣！那肯定好看！发出来看看[旺柴]",
                "哇哇哇，听起来就很绝！拍了多久啊？",
            ],
        },
        {
            "user": "好烦啊今天好多事",
            "replies": [
                "哈哈哈哈心疼你一秒 剩下的59秒先笑为敬[捂脸]",
                "咋了嘛，说出来让我开心一下[坏笑]",
            ],
        },
        {
            "user": "刚养了一只小猫，太可爱了",
            "replies": [
                "靠 有猫了不起啊！",
                "[大哭][大哭]我也想rua！快发照片！！",
            ],
        },
        {
            "user": "年糕把我的拖鞋咬坏了",
            "replies": [
                "哈哈哈哈哈哈哈笑死",
                "好家伙 这狗有品味 专挑贵的咬是吧[旺柴]",
            ],
        },
        {
            "user": "这张照片拍得怎么样",
            "replies": [
                "嗯…比上次好一点点吧 就一点点[嘿哈]",
                "好看！认真说 真的好看 我好喜欢",
            ],
        },
    ])
    # M-001: 记忆固化统一调用开关。True = 常规 L1 批次合并 3 次 LLM
    # 调用为 1 次；False = 走旧三次调用路径（灰度回退）。
    consolidation_unified_call: bool = True
    # Web security: extra allowed CORS origins beyond localhost
    allowed_origins: list[str] = field(default_factory=list)


CONFIG_PATH = "config.json"

_CACHED_CONFIG: Config | None = None


def load_config(path: str = CONFIG_PATH) -> Config:
    global _CACHED_CONFIG
    # CF-010: process-level cache for default config path to avoid re-reading
    # disk and logging on every tool call. Custom paths bypass cache.
    if path == CONFIG_PATH and _CACHED_CONFIG is not None:
        return _CACHED_CONFIG

    cfg = Config()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            logger.info(f"[config] loaded from: {path}")
        except (json.JSONDecodeError, OSError):
            logger.warning(f"[config] failed to parse: {path}, using defaults")
    else:
        logger.info(f"[config] no file at: {path}, using defaults")

    # CF-009: complete env var map — every config field with an env override
    env_map = {
        "DEEPSEEK_API_KEY": "api_key",
        "DEEPSEEK_API_ENDPOINT": "api_endpoint",
        "DEEPSEEK_API_MODEL": "api_model",
        "AI_FRIEND_DB_PATH": "db_path",
        "AI_FRIEND_LOG_LEVEL": "log_level",
        "AI_FRIEND_TEMPERATURE": "temperature",
        "AI_FRIEND_MAX_TOKENS": "max_tokens",
        "AI_FRIEND_MAX_TOOL_ITERATIONS": "max_tool_iterations",
        "AI_FRIEND_DEGRADE_THRESHOLD": "degrade_threshold",
        "AI_FRIEND_MAX_FAKE_ACTIONS": "max_fake_actions",
        "AI_FRIEND_TIMEOUT": "api_timeout",
        "AI_FRIEND_TYPING_SPEED": "typing_speed",
        "AI_FRIEND_WEB_HOST": "web_host",
        "AI_FRIEND_WEB_ACCESS_TOKEN": "web_access_token",
        "AI_FRIEND_WEB_PORT": "web_port",
        "AI_FRIEND_EMBEDDING_ENDPOINT": "embedding_endpoint",
        "AI_FRIEND_EMBEDDING_DIM": "embedding_dim",
        "AI_FRIEND_SHORT_TERM_CAPACITY": "short_term_capacity",
        "AI_FRIEND_PERSONALITY_FILE": "personality_file",  # L-05
        "AI_FRIEND_PROMPT_CACHE_TTL": "prompt_cache_ttl_seconds",
        "AI_FRIEND_CONVERSATION_EXAMPLES_MAX_TURNS": "conversation_examples_max_turns",
    }
    for env_var, attr in env_map.items():
        val = os.environ.get(env_var, "")
        if val:
            masked = "***" if "KEY" in env_var else val
            logger.info(f"[config] env override: {env_var}={masked}")
            # Cast to the right type
            field_type = type(getattr(cfg, attr))
            try:
                typed = field_type(val)
            except (ValueError, TypeError):
                logger.warning(f"[config] cannot cast {val} to {field_type.__name__} for {attr}, skipping")
                continue
            setattr(cfg, attr, typed)

    _validate(cfg)
    if path == CONFIG_PATH:
        _CACHED_CONFIG = cfg
    return cfg


def reload_config(path: str = CONFIG_PATH) -> Config:
    """Force reload config from disk, clearing the process-level cache."""
    global _CACHED_CONFIG
    _CACHED_CONFIG = None
    return load_config(path)


def save_config(cfg: Config, path: str = CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: getattr(cfg, k) for k in cfg.__dataclass_fields__}, f, indent=2, ensure_ascii=False)
