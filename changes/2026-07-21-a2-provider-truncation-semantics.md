# A2：Provider 截断显式化（provider.md P0-1）

日期：2026-07-21

## 背景

`doc/refactor/systems/provider.md` P0-1：流式/非流式截断此前被静默当作成功返回——流超时、超 1MB、断流（缺 [DONE]）、`finish_reason=length` 全部返回半截内容，下游无从分辨。对 `response_format`（JSON 模式）调用，半截 JSON 会在下游表现为莫名其妙的解析失败。

## 改动（`core/provider.py`）

- `_do_request` 返回值改 `(content, meta)`：meta 含 `truncated` / `finish_reason` / `truncation_reason`。四种截断检测：
  - 非流式 `finish_reason == "length"`
  - 流式超时（deadline break）
  - 流式超 1MB
  - 流式缺 `[DONE]`（断流）
- **response_format 调用截断 → 新增 `TruncatedResponseError`**，与网络错误同级走 3 次重试；耗尽后报错，不再把半截 JSON 交给下游。
- **纯文本聊天路径保持现状**（半截回复好于报错），仅 `logger.warning` + monitor 记录。
- monitor（`core/monitor.py`）：`MonitorRecord` 新增可选字段 `truncated` / `finish_reason`（带默认值，旧记录兼容），`record_call` 透传。

## 测试（`tests/test_provider.py::TestTruncationSemantics`，+4）

- JSON 模式截断：3 次重试后报 ConnectionError，不记录成功记录
- 文本截断：返回半截 + `truncated=True` + `finish_reason=length` 入库
- 流缺 [DONE]：truncated 记录
- 流正常 [DONE]：不标截断

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**769 passed + 2 skipped**（765 → 769）

## 备注

- provider.md 中 P0-1 至此完成；该文档的 P0-2（embedding 托管）此前已由 embedding_server 生命周期管理覆盖，剩余「token 预算集中」为独立项。
- 监控面板如想显示 truncated 标记是 monitor.js 的小增强，未做。
