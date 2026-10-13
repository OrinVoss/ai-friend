# 修复 issue #327：health_check 增加 TTL 缓存

## 修改的文件
- `memory/embeddings.py`

## 修改原因
`retrieval.py:58` 注释自称缓存了探测结果但实际没有：`retrieve_for_query` 与 `lifecycle._embed_text` 每次都真实发 HTTP 健康探测（GET /health + 可能的 POST 探测），是每条用户消息路径上的同步性能税。

## 修改内容
- `EmbeddingEngine.health_check` 增加 10s TTL 缓存：成功结果短路；失败不缓存，服务恢复后下一次探测立即生效。
- 新增 `health_check_uncached()` 供需要真实探测的场景使用；启动自检循环因失败不缓存而不受影响。
- 验证：`pytest -k "embed or retrieval or lifecycle"` 108 passed, 2 skipped。
