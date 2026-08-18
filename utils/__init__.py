"""Shared small utilities."""
import re

# #309: session_id/role_id 会被直接拼进文件路径（personalities/*.json、
# data/.proactivity_state.* 等），必须禁止路径分隔符、".." 与绝对路径。
# 允许：字母、数字、下划线、连字符、CJK 字符，1-64 长。
_ID_PATTERN = re.compile(r"^[0-9A-Za-z_\-一-鿿]{1,64}$")


def is_valid_session_id(value) -> bool:
    """session_id / role_id 合法性：仅字母数字、_、-、CJK，1-64 字符。"""
    return isinstance(value, str) and bool(_ID_PATTERN.match(value))


def shingle_similarity(a: str, b: str) -> float:
    """2-gram 覆盖率相似度 |A∩B| / min(|A|,|B|)（0~1）——中文短文本近重复检测。

    用于写入侧去重（体验/挂念等）：逐字重复与"第三次挂科"vs"挂了三次"
    这类轻微改写都能命中，不依赖 embedding（语义去重失效时的廉价兜底）。
    比 Jaccard 对同长文本更宽容；短文本场景慎用高阈值。
    """
    def _shingles(s: str) -> set:
        s = (s or "").strip()
        if len(s) < 2:
            return {s} if s else set()
        return {s[i:i + 2] for i in range(len(s) - 1)}

    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 1.0 if sa == sb else 0.0
    return len(sa & sb) / min(len(sa), len(sb))
