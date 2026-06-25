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
    personality_file: str = "personality.json"
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
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    log_level: str = "INFO"
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
        "AI_FRIEND_TIMEOUT": "api_timeout",
        "AI_FRIEND_TYPING_SPEED": "typing_speed",
        "AI_FRIEND_WEB_HOST": "web_host",
        "AI_FRIEND_WEB_PORT": "web_port",
        "AI_FRIEND_EMBEDDING_ENDPOINT": "embedding_endpoint",
        "AI_FRIEND_EMBEDDING_DIM": "embedding_dim",
        "AI_FRIEND_SHORT_TERM_CAPACITY": "short_term_capacity",
        "AI_FRIEND_LOG_LEVEL": "log_level",
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
