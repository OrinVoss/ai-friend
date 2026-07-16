# 重构计划与进度

本目录集中存放 AI 朋友项目的系统性重构计划、当前进度、决策记录和待办事项。

## 目录结构

```
doc/refactor/
├── README.md                 # 本说明
├── self-system.md            # 【入口】自我系统：统一人格架构（六层方案的总装图）
├── enhancement-overview.md   # 系统增强总览：每个子系统的增强方案与状态索引
├── progress.md               # 当前重构进度总览
├── layer1-memory/            # Layer 1: Memory 生命周期重构
│   ├── README.md
│   ├── plan.md
│   └── progress.md
├── layer2-prompt/            # Layer 2: Prompt 分层与静态化
│   └── README.md
├── layer3-retrieval/         # Layer 3: 多阶段 Retrieval
│   └── README.md
├── layer4-agent/             # Layer 4: Agent Runtime 解耦（含独处循环三零件文档）
│   └── README.md
├── layer5-tool/              # Layer 5: Tool Agent 精简
│   └── README.md
├── layer6-personality/       # Layer 6: Personality / Session / 记忆绑定
│   └── README.md
├── systems/                  # 基础设施与接口系统增强（日志/模型/数据库/人格/情绪/Web/CLI）
└── decisions/                # 重要技术决策记录
```

**先读 `self-system.md`**：六层是建设顺序，自我系统是运行形态。理解整体应该长什么样，再看各层怎么建。

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
