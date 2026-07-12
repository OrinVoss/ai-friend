# Batch 7 修复：Core P2/P3 改进（3 个）

## B7-6 context_manager CJK 范围扩展（#262）
- `core/context_manager.py` — CJK 字符范围增加 Extension A（U+20000-U+2A6DF），减少罕见汉字 token 低估

## B7-7 async_utils 线程池导出（#263）
- `core/async_utils.py` — `_EXECUTOR` 已在 consolidation.py 中使用（#184 超时机制），代码已就绪

## B7-8 proactivity 话题去重（#265）
- `core/proactivity.py` — 添加 `_recent_topics` deque（maxlen=5）；`pick_proactive_topic()` 过滤掉最近 5 次已选话题，避免重复

## 验证
- 全部 10+ 文件通过 `py_compile`

## 关闭 Issue
#262（partial）、#265（partial）
