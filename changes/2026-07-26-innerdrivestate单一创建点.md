# 2026-07-26 InnerDriveState 收敛为单一创建点

## 修改原因

外部诊断指出 inner_drive_state 存在"初始化链断裂"：`session_factory.py` 与
`agent_wiring.py` 两处各自重复拼接 InnerDriveState 的参数（7 项配置映射写两遍）。
核实：生产路径只经 session_factory 创建（行为正确），wiring 的 fallback 仅服务
测试路径，但参数映射重复属实，存在两处漂移风险。

## 修改的文件

- `core/inner_drive_state.py`：新增 `create_inner_drive_state(config, session_id,
  embedding_engine)` 工厂函数（proactive_think_loop 关闭返回 None）。
- `core/session_factory.py`：改为调用工厂函数。
- `core/agent_wiring.py`：fallback 创建同样改走工厂函数，并补注释说明其为测试路径。

## 同批诊断的处理状态（逐条）

1. 状态分裂/双向依赖：诊断有失实——InnerDriveAgent 经**构造函数**接收实例
   （agent_wiring.py:72），并不读取 `agent._inner_drive_state`；该属性只被装配层
   （session_factory / agent_wiring）读写。本次经单一创建点收敛后，创建职责已唯一。
2. 初始化链断裂：本次修复（见上）。
3A. 异步嵌套：不成立（MemoryAgent.answer 本就是 async，run_async 即桥接，
    无嵌套路径，AU-004 防护已就位）。
3B. 双重过滤：文档化设计（Stage 1 轻量预筛省 LLM 调用），不改。
3C. 持锁 await：不成立（梦境在锁外生成），已加行为级护栏测试
    （tests/test_sleep_manager.py::TestDreamGeneratedOutsideLock）。

## 验证

- `python -m py_compile` 通过；`pytest tests/ --ignore=tests/real_api -q`：
  854 passed, 2 skipped（与改前一致，行为无变化）。
