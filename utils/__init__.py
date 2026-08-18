"""Shared small utilities."""
import re

# #309: session_id/role_id 会被直接拼进文件路径（personalities/*.json、
# data/.proactivity_state.* 等），必须禁止路径分隔符、".." 与绝对路径。
# 允许：字母、数字、下划线、连字符、CJK 字符，1-64 长。
_ID_PATTERN = re.compile(r"^[0-9A-Za-z_\-一-鿿]{1,64}$")


def is_valid_session_id(value) -> bool:
    """session_id / role_id 合法性：仅字母数字、_、-、CJK，1-64 字符。"""
    return isinstance(value, str) and bool(_ID_PATTERN.match(value))
