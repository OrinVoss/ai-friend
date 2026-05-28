from dataclasses import dataclass
import json
import os


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
        except (json.JSONDecodeError, OSError):
            pass

    # Environment variable overrides
    env_map = {
        "DEEPSEEK_API_KEY": "api_key",
        "DEEPSEEK_API_ENDPOINT": "api_endpoint",
        "DEEPSEEK_API_MODEL": "api_model",
        "AI_FRIEND_DB_PATH": "db_path",
        "AI_FRIEND_LOG_LEVEL": "log_level",
    }
    for env_var, attr in env_map.items():
        val = os.environ.get(env_var, "")
        if val:
            setattr(cfg, attr, val)

    return cfg


def save_config(cfg: Config, path: str = CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: getattr(cfg, k) for k in cfg.__dataclass_fields__}, f, indent=2, ensure_ascii=False)
