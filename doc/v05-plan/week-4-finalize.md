# 第4周：收尾（P2/P3 + 测试加固，~60 个）

**目标**：整个项目达到生产标准。300+ 测试、文档同步、v0.5 发布。

---

## Day 1-3：P2/P3 批量清理（40 个）

按文件批量处理，不改逻辑，仅改代码质量。每个文件一次性完成所有关联 P2/P3。

### storage/database.py（S-001~012）

- 添加 `os.chmod(dir, 0o700)` (Unix)
- WAL checkpoint 定时执行（每小时）
- 添加 CHECK 约束（布尔、范围）
- 方法文档补全

### storage/repository.py（R-003/018/019/024/025/027/028）

- `recall_count` 从 upsert 移到 search
- `_row_to_fact` 简化 `r.keys()` → `"fact_type" in r`
- `json.loads` 异常保护
- 同步包装器文档说明

### core/agent.py（AG-003/006/010/013/015）

- 删除死代码 import
- `_tool_call_history` 改用 `deque(maxlen=20)`
- `KeyError` 空 deque 保护
- `_max_tool_iterations` 改为可配置

### core/dispatcher.py（DI-001~009）

- `json.loads` 10KB 限制
- arguments 类型守卫
- import 移到顶部
- `logger.exception()` 替换 `str(e)`
- 输出截断 2000 字符
- `_normalize_args` 补全别名

### core/provider.py（PR-001/005/006/007/009/012/013/014）

- max_tokens 默认值对齐 config
- `verify=True` 显式声明
- `time.monotonic()` 替换 `time.time()`
- 流式响应 1MB 上限

### memory/consolidation.py（CO-001~010）

- import 移到模块顶部
- 删除重复 log
- 注释对齐
- 关系衰减因子

### models/personality.py（PS-003/005/008/013/015/016/019/022/023/024/025）

- Trait 范围验证
- 默认添加 humor/sass
- decay 关联 baseline
- 魔法数字命名常量
- `emotion_events` 改用 `deque(maxlen=20)`
- `to_dict`/`from_dict` 往返一致性

### ui/display.py（DP-001~011）

- UnicodeEncodeError 处理
- ANSI 兼容
- 死代码删除
- 默认值同步

---

## Day 4-5：测试补全

### 目标：250 → 300+ 测试

| 模块 | 新增测试 | 覆盖重点 |
|------|---------|---------|
| repository | +5 | commit 验证、session 隔离 |
| fact_checker | +5 | async resolve、矛盾检测 |
| retrieval | +3 | 剪枝回退、编码复用 |
| personality | +5 | 怨恨/基线/键名 |
| consolidation | +3 | 原子性、重复调用 |
| embeddings | +3 | 线程安全、降级 |
| web | +5 | Origin/CORS/消息大小 |
| agent | +3 | 兜底/持久化/异常重置 |
| notify | +2 | 注入/错误处理 |
| 其他 | +16 | config/provider/tools 边界测试 |

**合计**：+50 测试，目标 300+

---

## Day 6：文档 + 发布

### 文档同步

- `README.md`：测试数、模块列表、配置项
- `doc/architecture.md`：最新的架构图
- `doc/milestones-and-issues.md`：issue 关闭同步
- `doc/v05-plan/`：本计划移到 `completed/` 或归档

### v0.5 发布

- GitHub milestone v0.5 批量关闭
- Release notes 撰写：
  - 三层 Agent 架构稳定
  - FactChecker 虚假记忆修正
  - InnerDrive + 主动行为两级门控
  - session 隔离
  - 安全加固（Origin/SSRF/命令注入/路径穿越）
  - 250+ → 300+ 测试

---

## Day 7：最终验证

- `python -m pytest tests/ -v --real-api`（全量 + 真实 API）
- Web 端 48h 稳定性检查
- CLI 端全功能回归
- 数据库迁移测试（旧 DB 升级到新 schema）

---

## 第4周风险总结

| 风险 | 等级 | 缓解 |
|------|------|------|
| 批量清理引入 regression | 中 | 每个文件修改后立即 pytest |
| 测试补全不足 | 低 | 聚焦核心路径 |
| v0.5 release notes 遗漏 | 低 | 从 commits 自动生成 |
