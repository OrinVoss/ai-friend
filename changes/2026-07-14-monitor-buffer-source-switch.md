# 监控面板优化：source 标签、200 条环形缓冲、自动刷新修复、可配置开关

## 问题

1. `provider.py` 里 `record_call(..., source="")` 导致监控面板每条记录的 source 都显示为空，无法区分是 Agent 1 / Agent 2 / Agent 3 / 梦境等哪个阶段产生的调用。
2. `core/monitor.py` 的 docstring 写"不设条数限制"，但提交信息要求"环形缓冲（200 条）"，代码实际是普通 list，长期运行内存会无限增长。
3. `web/static/monitor.html` 的"自动刷新"按钮没有绑定 `toggleAuto()`，点了只是改变量，不会真正启动定时器。
4. 监控默认全开且不可关闭，生产环境有泄露完整 prompt 的风险。

## 修改

### 1. source 字段不再是空字符串

- `LLMProvider.generate` / `DeepSeekProvider.generate` 新增可选参数 `source: str = ""`。
- 成功调用后把 `source` 传给 `record_call()`。
- 各调用点传入具体来源：
  - `inner_drive` → `assess`
  - `inner_drive.review` → `review`
  - `inner_drive.re_decide` → `re_decide`
  - `inner_drive.assess_agent3_intent` → `assess_intent`
  - `inner_drive.assess_proactive` → `proactive`
  - `tool_agent` → `tool_agent`
  - `Agent._react_loop` → `react`
  - `cli_controller` 的 react → `cli_react`
  - `ContextManager.compress` → `context_compress`
  - `SleepManager.generate_dream` → `dream`
  - `web/session` 的 llm_gen → `session`
  - `main.py` 的 consolidation wrapper → `consolidation`
  - `main.py` 的 rerank wrapper → `rerank`

### 2. 200 条环形缓冲

- `MonitorBuffer` 改为 `deque(maxlen=200)` 作为默认实现。
- 新增 `max_size` 属性，支持运行时调整大小。
- 修正 docstring，与实现一致：默认保留最近 200 条，可设为 0 不限制。

### 3. 自动刷新按钮修复

- `monitor.html` 的"自动刷新"按钮改为 `onclick="toggleAuto()"`。
- `toggleAuto()` 内部同时更新按钮文字和状态栏，避免状态和 UI 不一致。

### 4. 可配置开关

- `Config` 新增 `monitor_enabled: bool = True`。
- `config.example.json` 与 `config.json` 增加 `"monitor_enabled": true`。
- `DeepSeekProvider.__init__` 接收 `monitor_enabled`，并调用 `set_monitor_enabled()` 控制是否记录新调用。
- `main.py`、`web/session.py` 创建 provider 时从 config 传入开关。

## 验证

- 单元测试：`python -m pytest tests/test_provider.py tests/test_provider_abc.py tests/test_inner_drive.py tests/test_message_handler.py -v` 全部通过（59 passed）。
- 全量测试：`python -m pytest tests --ignore=tests/real_api -q` 通过（366 passed）。

## 重启服务

修改后需要重启 Web 服务才能生效。当前服务 PID 30508，重启命令：

```bash
kill 30508
nohup .venv/Scripts/python.exe web_main.py > logs/web_service.log 2>&1 &
```
