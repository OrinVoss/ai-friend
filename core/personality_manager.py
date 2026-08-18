"""角色统一管理（Layer 6）：personalities/ 目录是唯一数据源。"""
import logging
import os
from pathlib import Path

from core.personality import Personality

logger = logging.getLogger(__name__)


class PersonalityManager:
    def __init__(self, personality_dir: str = "personalities"):
        self._dir = Path(personality_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_role_id(role_id: str) -> None:
        """#309: role_id 会拼进文件路径，拒绝路径穿越字符（纵深防御，
        Web 入口 SessionManager 已有一层校验）。"""
        from utils import is_valid_session_id
        if not is_valid_session_id(role_id):
            raise ValueError(f"invalid role_id: {role_id!r}")

    def personality_path(self, role_id: str) -> str:
        self._validate_role_id(role_id)
        return str(self._dir / f"{role_id}.json")

    def list_roles(self) -> list[str]:
        """personalities/*.json（排除 .bak）的文件名即 role_id。"""
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def role_exists(self, role_id: str) -> bool:
        self._validate_role_id(role_id)
        return (self._dir / f"{role_id}.json").exists()

    def load_role(self, role_id: str) -> Personality:
        """加载角色完整状态（个性 + 情绪）。不存在则抛 FileNotFoundError。"""
        path = self.personality_path(role_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Role file not found: {path}")
        # A4: 加载前校验——拼错字段/越界值全部进日志（此前静默失效）
        from core.personality_validator import (log_issues,
                                                validate_personality_file)
        log_issues(path, validate_personality_file(path))
        return Personality.load(path)

    def save_role(self, role_id: str, personality: Personality) -> None:
        personality.save(self.personality_path(role_id))

    def create_role(self, role_id: str, base: Personality | None = None) -> Personality:
        """以 default 为模板创建新角色（base 为空时读 default.json）。
        已存在则抛 FileExistsError。"""
        self._validate_role_id(role_id)  # #309
        path = self._dir / f"{role_id}.json"
        if path.exists():
            raise FileExistsError(f"Role already exists: {role_id}")
        if base is None:
            base = self.load_role("default")
        base.save(str(path))
        logger.info(f"[personality_manager] created role: {role_id}")
        return base
