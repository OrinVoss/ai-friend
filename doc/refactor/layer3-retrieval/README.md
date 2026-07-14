# Layer 3: 多阶段 Retrieval

## 目标

从单一的 "Embedding TopK" 改成多阶段检索，让不同 Agent 拿到不同粒度、不同来源的上下文。

## 当前状态

未开始。

## 关键问题

- 所有 Agent 共享同一个 Context
- Tool Agent 读取了不需要的人格/情绪/共同回忆
- Reflection 直接被 React 读取，容易自我强化

## 预期方向

```
Query → Intent → Fact → Episode → Reflection → Rank → Context Builder
```

不同 Agent 使用不同 Retrieval：

- React：只读 Fact + Episode
- Planner：读 Fact + Episode + Reflection
- Fact Extractor：读 Episode
- Tool Agent：不读 Memory

## 依赖

- Layer 1 完成 Fact/Observation 分层
- Layer 2 完成 Prompt 静态化，否则 Context Builder 收益有限
