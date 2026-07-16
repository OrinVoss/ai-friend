# 统一管线 P1：ConversationEngine + CLI 灰度开关

对应 `doc/refactor/systems/unified-pipeline.md` 的 P1（管线统一）。CLI 和 Web 从「两台走消息的机器」变成「一个引擎、两个前端」——开关灰度期间旧路径原样保留。

## 改动

- `core/conversation_engine.py`（新建）
  - `Frontend` 基类：`on_token / on_message_done / on_proactive / on_sleep_reply / on_status / on_error` 全部默认 no-op，前端只重写自己渲染的事件；引擎只发清理后的事件，原始流和工具标记不接触前端
  - `ConversationEngine`：Agent + MessageHandler 的薄包装，无自有状态
    - `handle_message(input, fe)`：on_token 透传流式首轮；完成时按睡眠与否发 on_message_done / on_sleep_reply；异常发 on_error 并返回空串
    - `handle_proactive / handle_explore`：产出才发 on_proactive（探索沉默不发事件）
    - `get_sleep_state / get_emotion_summary / get_relationship`：供命令层与状态查询
- `core/cli_controller.py`
  - `run()` 顶部加 UP-001 分支：`config.cli_shared_pipeline=true` 走 `_run_shared_pipeline()`，否则旧状态机（行为不变）
  - 新增 `_run_shared_pipeline()`：启动横幅/问候语复用 `_on_boot`，循环 = 读输入 → `/` 命令照旧 → `engine.handle_message`；每 10 轮保存人格；Ctrl-C 与 `/exit` 都进 `_on_shutdown`
  - 新增 `_CliFrontend(Frontend)`：打字机流式（首 token 懒打名字前缀）；未流式的回复（工具轮后）在 done 时整体渲染；睡眠回复/错误走 display
  - **旧内联 ReAct 状态机保留**——P3 灰度验证后再删
- `config.py` / `config.example.json`：新增 `cli_shared_pipeline: bool = false`（灰度开关，不走 env_map——bool 字符串转换有坑）
- `tests/test_unified_pipeline.py`（新建，13 用例）：
  - 引擎事件序列（done / sleep_reply / proactive / error / 探索沉默无事件）
  - **等价性**：同一输入，CLI mock 前端与 Web mock 前端收到相同事件序列
  - **开关回退**：flag off 走旧路径、flag on 走新引擎
  - `_CliFrontend` 渲染：流式不重复渲染、未流式整体渲染、睡眠回复
  - 附带踩坑记录：绑定方法每次访问都是新对象，断言回调用 `assertEqual`/`__self__` 而非 `assertIs`
- `doc/refactor/systems/unified-pipeline.md`：P1 标记完成、验收 1/3 打勾、顺带解决项更新
- `doc/config-reference.md`：杂项表新增 `cli_shared_pipeline`
- `README.md` / `doc/architecture.md`：core 17 → 18 模块；README 测试 435 用例 / 34 文件 + 统一管线特性条

## 开关开启后 CLI 获得什么

情绪更新（`_process_emotion` 接入，CLI 情绪不再永恒不变）、Agent 1 短输入跳过、context_summary 复用、Prompt 分层缓存、Agent 3 intent 审批循环——这些原本只有 Web 有。

## 测试

- 新增 13 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **435 passed, 2 skipped**（基线 422）

## 后续

- 灰度验证：`config.json` 设 `cli_shared_pipeline: true` 日常使用几天，对比两端行为
- P2 Runtime 下沉：主动/睡眠循环抽 `RuntimeDriver`，CLI 获得主动行为与做梦
- P3 收尾：删 CliController 旧状态机、Web `_split_segments` 死代码；开关翻默认 true 后移除
