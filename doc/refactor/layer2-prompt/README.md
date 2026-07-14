# Layer 2: Prompt 分层与静态化

## 目标

把系统提示拆成"静态块 / 慢变块 / 动态块"，只重建真正变化的部分；减少单次请求中重复构建系统提示的开销。

## 当前状态

未开始。

## 关键问题

- `build_system_prompt()` 单次调用涉及时间格式化、人格序列化、情绪描述、关系数据、长期记忆等，字符量 15000-40000
- Agent 1 / Agent 2 / Agent 3 各自重建完整人格/情绪/记忆上下文
- 静态对话示例每轮重复发送

## 预期方向

1. 新增 `core/prompt_cache.py`：静态块无 TTL，慢变块 TTL 60 秒
2. 拆分 `prompts/system.py` 的构建函数为独立 block
3. Agent 1 判断后把已格式化的记忆/关系摘要传给 Agent 3
4. 短输入直接跳过 Agent 1 LLM 调用

## 依赖

- Layer 1 Memory 生命周期稳定后，Memory Context 的摘要格式才能固定
