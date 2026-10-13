# 修复 issue #324：prune_facts 只衰减不删行

## 修改的文件
- `storage/repository.py`

## 修改原因
`prune_facts` 超出上限时仅对最低分溢出行 `freshness/confidence × 0.1`，行数不变 → 下次 consolidation 仍超限 → 同一批行被反复 ×0.1，active 表只涨不缩，"prune" 名不副实。

## 修改内容
- `prune_facts` 改为与 `prune_insights` 一致的软删语义：溢出行置 `status='expired'`，active 行数真正收敛到上限内。
- 被重新提及的事实可通过 upsert 的 #217 复活语义回到 active。
- 验证：`pytest -k "prune or repository"` 38 passed；无测试断言旧的 ×0.1 行为。
