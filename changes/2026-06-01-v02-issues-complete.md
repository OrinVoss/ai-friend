# 2026-06-01 - v0.2 全部 issue 根本解决

## 修改文件

### 新建
- **tests/test_v02_issues.py** — 14 个单元测试覆盖全部 5 个 issue

### 修改
- **memory/retrieval.py** — #21: `_score_facts` 不再原地修改 `composite_score`
- **memory/consolidation.py** — #22: `add_pending` 按 (turn_id, role) 去重；#5: 三级反思 L1/L2/L3
- **core/personality.py** — #20: humor/sass 特质生效（情绪调制）
- **prompts/templates.py** — #5: L2 模式识别 + L3 深度洞察提示词
- **storage/database.py** — #40: 5 个表加 `session_id` 字段迁移
- **storage/repository.py** — #40: 所有查询加 `session_id` 过滤，写入带 session_id
- **web/session.py** — #40: WebAgent 设置 `repo.session_id`

## 解决的 issue

| # | 标题 | 修复内容 |
|---|------|---------|
| #5 | 分层反思 | L1 事实(每次) → L2 模式(每3次) → L3 深度洞察(每10次) |
| #20 | humor/sass 无实际效果 | humor 减轻 sadness 影响 + 增加正面倾向；sass 减少 anger 增量 + 轻度负面激发 joy |
| #21 | _score_facts 原地覆写 | 不再修改传入的 UserFact，改用元组排序 |
| #22 | pending 重复 | add_pending 按 (turn_id, role) 去重 |
| #40 | 无 session 隔离 | 5 表加 session_id 列 + Repository 过滤 + WebAgent 透传 |

## 测试
264 passed (+14), 8 skipped
