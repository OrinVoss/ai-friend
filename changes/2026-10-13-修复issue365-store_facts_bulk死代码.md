# 修复 issue #365：store_facts_bulk 死代码清理

## 修改的文件
- `storage/repository.py`
- `memory/long_term.py`
- `tests/test_repository.py`

## 修改原因
`store_facts_bulk` 生产路径无调用方（consolidation 已改逐条 promote_fact），只剩 tests 在测死代码，徒增维护面。

## 修改内容
- 删除 `repository.store_facts_bulk`、`long_term._store_facts_bulk/store_facts_bulk` 及测试类 `TestStoreFactsBulk`。
- `test_consolidation.py` 中对 mock 的 `assert_not_called` 断言不受影响。
- 验证：`pytest tests/test_repository.py tests/test_consolidation.py` 66 passed。
