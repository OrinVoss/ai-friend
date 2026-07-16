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
    if cfg.agent1_short_input_threshold < 0:
        messages.append(f"agent1_short_input_threshold {cfg.agent1_short_input_threshold} < 0, clamped to 20")
        cfg.agent1_short_input_threshold = 20
    if cfg.conversation_examples_max_turns < 0:
        messages.append(f"conversation_examples_max_turns {cfg.conversation_examples_max_turns} < 0, clamped to 3")
        cfg.conversation_examples_max_turns = 3
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
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    log_level: str = "INFO"
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
    agent1_short_input_threshold: int = 20
    conversation_examples_max_turns: int = 3
    # ML-001: Layer 1 Memory lifecycle switch
    use_observation_fact: bool = False
    # UP-001: unified-pipeline P1 gray switch — CLI runs over the shared
    # ConversationEngine (same pipeline as Web) instead of the legacy
    # CliController inline state machine.
    cli_shared_pipeline: bool = False
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
    # Web security: extra allowed CORS origins beyond localhost
    allowed_origins: list[str] = field(default_factory=list)


CONFIG_PATH = "config.json"


def load_config(path: str = CONFIG_PATH) -> Config:
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
        "AI_FRIEND_TIMEOUT": "api_timeout",
        "AI_FRIEND_TYPING_SPEED": "typing_speed",
        "AI_FRIEND_WEB_HOST": "web_host",
        "AI_FRIEND_WEB_PORT": "web_port",
        "AI_FRIEND_EMBEDDING_ENDPOINT": "embedding_endpoint",
        "AI_FRIEND_EMBEDDING_DIM": "embedding_dim",
        "AI_FRIEND_SHORT_TERM_CAPACITY": "short_term_capacity",
        "AI_FRIEND_LOG_LEVEL": "log_level",
        "AI_FRIEND_PROMPT_CACHE_TTL": "prompt_cache_ttl_seconds",
        "AI_FRIEND_AGENT1_SHORT_INPUT_THRESHOLD": "agent1_short_input_threshold",
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
    return cfg


def save_config(cfg: Config, path: str = CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: getattr(cfg, k) for k in cfg.__dataclass_fields__}, f, indent=2, ensure_ascii=False)
