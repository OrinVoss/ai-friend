# Layer 6 角色绑定 — 实施计划（供低成本模型执行，详版）

> 日期：2026-07-20。依据：`doc/refactor/layer6-personality/README.md`（设计）+ 代码现状核对。
> 本文档面向执行者：**所有需要知道的信息都在本文里**。严格按项执行，不做清单之外的"顺手优化"。
> 项目：D:/桌面/编程作品/AI朋友，Python 3.13，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **693 用例（691 passed + 2 skipped）**，改完必须全绿且不减少。

---

## 0. 现状核对（先看懂再动手）

设计的核心原则 `role_id == session_id == memory_namespace == emotion_namespace == sleep_namespace` **约 60% 已经落地**，本计划是收口而不是从零搭建：

| 设计项 | 现状 | 差距 |
|--------|------|------|
| personalities/{role_id}.json 含个性+情绪 | ✅ 已是 `{"personality": {...}, "emotional_state": {...}}`（注意顶层键是 `personality` 不是设计稿的 `config`，**以实际为准不改**）。H-06：save 先读盘合并再写回；#291：RLock 保护 | 只剩根目录 `personality.json` 遗留 |
| session→role 绑定 | ✅ `session_roles` 表（storage/database.py:185）+ #SR-002 迁移（:364-430，把 default session 数据搬到 role_id、清理旧 session）。Web 端 `[session] create: 小星 role=小星` | 没有**强制**：Repository.session_id 是普通属性，可赋任意值 |
| 记忆按 session 隔离 | ✅ 所有表都有 session_id 且查询按它过滤（schema v3 起） | 缺多角色切换的隔离验证测试 |
| 睡眠状态 | ✅ `.sleep_state.{session_id}` per-session 文件（core/sleep_manager.py） | 无（session_id==role_id 后即满足） |
| PersonalityManager 统一 API | ❌ 不存在。现在是 `Personality.load/save`（core/personality.py:119,153）+ 各处自行拼路径 | 需要新建 |
| 根目录 personality.json | ⚠️ 文件仍在仓库里，config 默认已是 `personalities/default.json`（config.py:51） | 确认无引用后删除 |

---

## L6-1：PersonalityManager（`core/personality_manager.py`，新建）

**根因**：角色文件的加载/保存/枚举/创建逻辑散落在 `main.py`、`web_main.py`、`web/session.py`、`core/session_factory.py`，每次新增角色支持都要改多处。

**做法**：

```python
"""角色统一管理（Layer 6）：personalities/ 目录是唯一数据源。"""
import json
import logging
from pathlib import Path

from core.personality import Personality

logger = logging.getLogger(__name__)


class PersonalityManager:
    def __init__(self, personality_dir: str = "personalities"):
        self._dir = Path(personality_dir)

    def personality_path(self, role_id: str) -> str:
        return str(self._dir / f"{role_id}.json")

    def list_roles(self) -> list[str]:
        """personalities/*.json（排除 .bak）的文件名即 role_id。"""
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def role_exists(self, role_id: str) -> bool:
        return (self._dir / f"{role_id}.json").exists()

    def load_role(self, role_id: str) -> Personality:
        """加载角色完整状态（个性 + 情绪）。不存在则抛 FileNotFoundError。"""
        return Personality.load(self.personality_path(role_id))

    def save_role(self, role_id: str, personality: Personality) -> None:
        personality.save(self.personality_path(role_id))

    def create_role(self, role_id: str, base: Personality | None = None) -> Personality:
        """以 default 为模板创建新角色（base 为空时读 default.json）。
        已存在则抛 FileExistsError。"""
```

- `PersonalityManager` 挂在哪：`core/session_factory.py::assemble_session` 目前接收 personality 参数，改为接收 `role_id` + 可选 `PersonalityManager`（默认自建），内部 `load_role`。调用方（main.py / web/session.py）相应改为传 role_id。
- `web/server.py` 的 `/api/roles` 端点如已有自己的目录扫描逻辑，改为调 `PersonalityManager.list_roles()`。

**测试**（`tests/test_personality_manager.py`）：tmp 目录造 default.json/小星.json → list_roles 排序正确且排除 .bak、load_role 往返一致、create_role 以 default 为模板、role_exists 边界、create 已存在抛错。

---

## L6-2：强制 session_id = role_id

**根因**：`storage/repository.py:17` 的 `self.session_id: str = "default"` 是普通属性，`core/session_factory.py:109` 直接赋值，没有任何东西阻止「session_id 与 role_id 不一致」。

**做法**：
1. `core/session_factory.py::assemble_session(config, db, session_id, role_id=None, ...)`：`role_id` 缺省时 `role_id = session_id`；两者不一致时 `raise ValueError`（Layer 6 强制绑定）。内部所有 `repo.session_id`、工具、consolidator、agent 的 session 一律用 `role_id`。
2. `web/session.py` 的 session 创建：`create(session_id, role_id)` 不一致时同样拒绝（现在日志 `create: 小星 role=小星` 已一致，加硬校验防回归）。
3. `set_session_role`（storage/repository.py）保持现状（迁移用），但新代码路径不允许写「session != role」的行。
4. **历史数据处理**：#SR-002 迁移已做（database.py:364-430），不动。

**测试**（`tests/test_session_factory.py` 追加）：session_id 与 role_id 不一致 → ValueError；一致时正常装配；`web/session.py` 侧不一致创建被拒。

---

## L6-3：废弃根目录 personality.json

**做法**：
1. 全仓搜索 `personality.json`（不含 `personalities/`）的代码引用——预期为零（config.py:51 默认已是 `personalities/default.json`）。若有引用，改为 personality_manager。
2. 从 git 删除 `personality.json` 文件本身（`git rm`，保留在 .gitignore 防本地再生成？——不需要，它不是运行时生成的）。
3. `README.md`/`doc/` 里如果有 `personality.json`（根目录）的描述，同步改成 `personalities/{role_id}.json`。

**测试**：`grep -rn "personality\.json" --include=*.py .`（排除 personalities/）结果为空。

---

## L6-4：多角色隔离验证测试（`tests/test_role_isolation.py`，新建）

**目的**：设计的验收标准第 1、2 条——切换角色后 memory/relationship/sleep 完全隔离。这是整个 Layer 6 的验收核心，**只写测试不改实现**（发现隔离漏洞才修，并把漏洞写进 changes）。

**做法**：真实临时 SQLite（参照 `tests/test_memory_agent_real_db.py` 的模式）：

```python
"""多角色数据隔离验证（Layer 6 验收）。"""
import asyncio, tempfile, unittest
from storage.database import Database
from storage.repository import Repository


class TestRoleIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(f"{self._tmp.name}/t.db", backup_enabled=False)
        asyncio.run(self.db.open())

    def tearDown(self):
        asyncio.run(self.db.close())
        self._tmp.cleanup()

    def _repo(self, role):
        r = Repository(self.db)
        r.session_id = role
        return r

    def test_facts_isolated_by_role(self):
        a, b = self._repo("角色A"), self._repo("角色B")
        asyncio.run(a.upsert_fact_v2("preference", "最爱食物", "披萨"))
        asyncio.run(b.upsert_fact_v2("preference", "最爱食物", "寿司"))
        fa = asyncio.run(a.get_active_facts_v2())
        fb = asyncio.run(b.get_active_facts_v2())
        self.assertEqual(fa[0].fact_value, "披萨")
        self.assertEqual(fb[0].fact_value, "寿司")
        # A 的检索看不到 B 的事实
        self.assertEqual(len(asyncio.run(a.search_facts_v2("寿司"))), 0)

    def test_relationship_isolated_by_role(self):
        ...

    def test_turns_isolated_by_role(self):
        ...

    def test_insights_isolated_by_role(self):
        ...
```

- 睡眠状态隔离：构造两个 `SleepManager`（不同 sleep_state_file）验证互不影响（如已有此类测试则跳过，先 grep tests/）。
- 如发现某条查询漏了 session 过滤：**记录为 bug 并在本项内修复**（这属于计划内工作，不是顺手优化）。

---

## L6-5：文档收尾

- `doc/refactor/layer6-personality/README.md` + `progress.md`：状态改「已实现（2026-07-2X）」，Step 1-5 打勾（Step 1/3 注明「此前已部分落地（session_roles/情绪持久化），本次收口」）
- `doc/refactor/progress.md`：Layer 6 行更新
- `doc/architecture.md`：角色绑定段落更新（PersonalityManager + 强制 session==role）
- 新建 `changes/2026-07-2X-layer6-role-binding.md`：现状核对表、强制绑定点、隔离验证结果

---

## 明确不做

- **不改 personalities 文件的顶层键名**（实际是 `personality` 不是设计稿的 `config`——以代码为准）
- **不支持同角色多 session**（设计原则就是一一对应；未来如需再立项）
- **不做角色管理 Web UI**（API list_roles 已够本期）
- **不动 session_roles 迁移逻辑**（#SR-002 已在生产跑过）
- **不做向量库跨角色共享**（embedding 按 session 隔离现状即满足）

## 执行顺序与验收总表

| 顺序 | 项 | 风险 | 关键验收 |
|------|----|------|----------|
| 1 | L6-1 PersonalityManager | 低 | list/load/create 测试全绿 |
| 2 | L6-2 强制绑定 | 中（改装配入口） | 不一致即 ValueError，现有 CLI/Web 启动不受影响 |
| 3 | L6-3 删 personality.json | 低 | 代码引用为零 |
| 4 | L6-4 隔离验证 | 低（纯测试） | 四张表 + 睡眠隔离全绿 |
| 5 | L6-5 文档 | 无 | changes + 打勾 |

全部完成后：`python -m pytest tests --ignore=tests/real_api -q` 全绿（≥693 用例）。
