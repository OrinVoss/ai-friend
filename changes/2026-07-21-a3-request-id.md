# A3：request_id 全链路日志关联（logging.md P1-4/P1-6）

日期：2026-07-21

## 背景

多 session 并发 + 状态轮询时日志交错，还原一条消息的完整链路只能按时间戳肉眼对齐；monitor 记录时间戳只有时分秒，跨天无法对齐。按 `doc/refactor/systems/logging.md` 实现请求级 request_id。

## 改动

- `core/logging_setup.py`：模块级 `request_id_var`（ContextVar）+ `new_request_id()`（uuid4 前 8 位）+ `RequestIdFilter`（注入每条 record，空显示 `-`）；两个 handler 的 formatter 增加 `%(request_id)s` 字段（不破坏现有行格式）
- `core/async_utils.py::run_async`：桥接分支用 `contextvars.copy_context()` 显式传播——ThreadPoolExecutor 不会自动携带 ContextVar，request_id 需要随任务进入 worker 线程（否则 Web 路径下 `run_async` 之后的日志全部丢 id）
- 设置点：
  - `web/server.py::_token_auth` 中间件：每个 HTTP 请求一个 id，finally 复位
  - `web/server.py` WS 循环：每个 message 帧一个 id（init 握手不算）
  - `core/message_handler.py::handle_message`：CLI 路径入口，仅在未设置时生成。无需复位——后台 tick 在独立线程/任务的 context 里，天然显示 `-`（三个生命循环的边界即 context 边界）
- `core/monitor.py`：`MonitorRecord` 新增 `request_id`（record_call 从 ContextVar 读）；timestamp 从 `%H:%M:%S` 改为含日期

## 效果

`grep <request_id>` 一次捞出 `[ws]→[msg]→[inner_drive]→[tool]→[api]→[db]` 全链路；独处/睡眠循环日志显示 `-`，与请求驱动日志自然区分。monitor 面板的慢调用可拿 id 回日志捞全链路。

## 测试（`tests/test_request_id.py`，+5）

- Filter 空值显示 `-`、有值注入、id 格式
- record_call 读 ContextVar + 时间戳含日期
- run_async 桥接传播 context 到 worker 线程

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**774 passed + 2 skipped**（769 → 774）
