# 重构计划与进度

本目录集中存放 AI 朋友项目的系统性重构计划、当前进度、决策记录和待办事项。

## 目录结构

```
doc/refactor/
├── README.md                 # 本说明
├── progress.md               # 当前重构进度总览
├── layer1-memory/            # Layer 1: Memory 生命周期重构
│   ├── README.md
│   ├── plan.md
│   └── progress.md
├── layer2-prompt/            # Layer 2: Prompt 分层与静态化
│   └── README.md
├── layer3-retrieval/         # Layer 3: 多阶段 Retrieval
│   └── README.md
├── layer4-agent/             # Layer 4: Agent Runtime 解耦
│   └── README.md
├── layer5-tool/              # Layer 5: Tool Agent 精简
│   └── README.md
├── layer6-personality/       # Layer 6: Personality / Session / 记忆绑定
│   └── README.md
└── decisions/                # 重要技术决策记录
```

## 当前总览

| Layer | 主题 | 状态 | 负责人 |
|-------|------|------|--------|
| Layer 1 | Memory 生命周期（Observation → Fact → Insight） | 一期已完成，双写阶段 | Kimi |
| Layer 2 | Prompt 分层与静态化 | 未开始 | - |
| Layer 3 | 多阶段 Retrieval | 未开始 | - |
| Layer 4 | Agent Runtime 解耦 | 未开始 | - |
| Layer 5 | Tool Agent 精简 | 未开始 | - |
| Layer 6 | Personality / Session / 记忆绑定 | 未开始 | - |

## 使用方式

- 每个 Layer 一个独立文件夹，记录目标、方案、当前状态、阻塞项。
- `progress.md` 每周更新一次，汇总各 Layer 进度。
- 重要技术决策写入 `decisions/YYYY-MM-DD-主题.md`。
