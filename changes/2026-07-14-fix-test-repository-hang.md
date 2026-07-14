# 修复 tests/test_repository.py 在 pytest 下卡死

## 问题

全量测试时 `tests/test_repository.py` 会无限卡住：

```bash
python -m pytest tests/test_repository.py -q
# 卡住，无输出
```

但同样逻辑直接 `python -c` 跑完全正常。

## 根因

原测试在 `setUpClass` 里用 `asyncio.run(cls.db.open())` 创建 aiosqlite 连接，然后在 `setUp` / 各 test 方法里又用新的 `asyncio.run()` 操作同一个连接。

aiosqlite 0.22.1 的 SQLite 连接与创建它的 event loop 绑定，跨 loop 复用会导致死锁，因此 pytest 执行时卡死。

## 改动

`tests/test_repository.py`：

- 移除三个 test class（`TestRepositoryFacts`、`TestRepositoryRelationship`、`TestRepositorySessionRole`）的 `setUpClass`。
- 改为每个 test 的 `setUp` 里新建 `:memory:` 数据库、打开连接、创建 `Repository`。
- 新增 `tearDown` 关闭连接。
- 保留原 `setUp` 中的表清理逻辑。

这样每个 test 自包含，整个生命周期都在同一个 event loop 内完成。

## 验证

```bash
python -m pytest tests/test_repository.py -v
# 17 passed in 0.28s

python -m pytest tests --ignore=tests/real_api -q
# 389 passed, 2 skipped in 37.74s
```

## 相关文件

- `tests/test_repository.py`
- `changes/2026-07-14-complete-294-p2-5-runtime-summary.md`（已同步更新验证结果）
