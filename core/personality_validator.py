"""人格文件校验器（A4，2026-07-21，systems/personality.md P1-4）。

拼错的字段名/特质名此前静默失效（from_dict 只取已知字段），损坏文件
静默退默认人格——手改 JSON 的错误完全没有可见性。校验器返回问题列表
（warning 级，不抛异常），由 PersonalityManager 在加载时报告。
"""
import json
import logging

from models.personality import PersonalityConfig

logger = logging.getLogger(__name__)

KNOWN_TOP_LEVEL = {"personality", "emotional_state", "id", "version"}


def validate_personality_data(data, source: str = "") -> list[str]:
    """校验人格数据，返回问题列表（空列表 = 无问题）。"""
    issues: list[str] = []
    if not isinstance(data, dict):
        return ["顶层不是 JSON object"]
    for k in data:
        if k not in KNOWN_TOP_LEVEL:
            issues.append(f"未知顶层字段: {k!r}")

    p = data.get("personality", data)  # 兼容裸 config 结构
    if not isinstance(p, dict):
        issues.append("personality 字段不是 object")
        return issues

    known = set(PersonalityConfig.__dataclass_fields__)
    for k in p:
        if k not in known:
            issues.append(f"未知 personality 字段（疑似拼写错误）: {k!r}")

    if not p.get("name"):
        issues.append("缺少 name 或为空")

    traits = p.get("traits")
    if traits is not None:
        if isinstance(traits, dict):
            items = list(traits.items())
        elif isinstance(traits, list):
            items = [(t.get("name"), t.get("value"))
                     for t in traits if isinstance(t, dict)]
        else:
            items = []
            issues.append(f"traits 结构不可识别: {type(traits).__name__}")
        for name, value in items:
            if not name:
                issues.append("traits 存在空名字条目")
                continue
            try:
                v = float(value)
                if not 0.0 <= v <= 1.0:
                    issues.append(f"trait {name!r} 值 {v} 越界 [0,1]")
            except (TypeError, ValueError):
                issues.append(f"trait {name!r} 值不可解析: {value!r}")

    baseline = p.get("emotional_baseline")
    if baseline is not None:
        if (not isinstance(baseline, dict)
                or not all(k in baseline for k in ("valence", "arousal"))):
            issues.append("emotional_baseline 结构不完整（需要 valence/arousal）")

    decay = p.get("emotional_decay_rate")
    if decay is not None:
        try:
            if not 0.0 <= float(decay) <= 1.0:
                issues.append(f"emotional_decay_rate 越界: {decay}")
        except (TypeError, ValueError):
            issues.append(f"emotional_decay_rate 不可解析: {decay!r}")

    e = data.get("emotional_state")
    if e is not None and not isinstance(e, dict):
        issues.append("emotional_state 字段不是 object")

    return issues


def validate_personality_file(path: str) -> list[str]:
    """读取并校验人格文件；文件损坏时返回单条错误。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return [f"文件无法解析: {e}"]
    return validate_personality_data(data, source=path)


def log_issues(path: str, issues: list[str]) -> None:
    """统一报告入口：每个问题一条 warning。"""
    for issue in issues:
        logger.warning(f"[personality.validate] {path}: {issue}")
