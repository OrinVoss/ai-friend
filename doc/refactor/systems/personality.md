# 人格系统增强方案

> 目标：把人格内容从「手改 JSON、无校验、会被运行时覆盖」升级为可安全编辑、可校验、可最小演化的人格内容生命周期管理。
> 状态：设计文档，待实现。
> 归属：系统增强（systems/）。与 Layer 6 互补——Layer 6 管「人格属于谁」（角色与 session 绑定），本文档管「人格内容怎么管」（管理、校验、编辑、演化）。

---

## 1. 现状盘点

| 方面 | 现状 |
|------|------|
| 载体 | `personalities/{role}.json`，人格定义（`personality`）与情绪运行时状态（`emotional_state`）**同文件** |
| 加载 | `Personality.load()`（`core/personality.py:100`）：CLI 启动时一次（`main.py:44`），Web 每个新会话一次（`web/session.py:46`） |
| 保存 | 全量 `to_dict()` 覆盖写（`core/personality.py:134-144`，原子写 #153/#206）。触发点：Web 每次消息处理后 30s 防抖（`web/session.py:114-125`）、关闭/淘汰/ shutdown（`web/session.py:127-137`、`246-251`、`394-401`）；CLI 每 10 轮 + `/save` + 退出（`core/cli_controller.py:343`、 `353`、 `367`） |
| 进 prompt | `_build_identity_block()`（`prompts/system.py:359-375`）静态拼接：traits 百分比 + speaking_style + backstory + interests，缓存 `ttl=None`，靠文件 mtime 失效（`core/prompt_cache.py:33-43`） |
| 风格示例 | `conversation_examples` 是**全局配置**（`config.py:83-119`），默认 5 组小星味互损示例，无差别注入所有角色（`core/message_handler.py:354`、`407`、`481` → `prompts/system.py:663`） |
| 新建角色 | `_ensure_personality_file()` 整文件复制模板 `personalities/default.json`，**连 `emotional_state` 一起**（`web/session.py:139-152`） |
| 编辑方式 | 手改 JSON + 重启，无校验、无工具；Web 只有只读的 `/api/roles`（`web/server.py:217-232`） |
| 备份 | 每次 `load()` 前把当前文件复制为 `.bak`（`core/personality.py:105-109`） |
| 校验 | `config.py` 有 `_validate()`（`config.py:10-37`）；人格文件**零校验**，`from_dict` 静默丢未知字段（`models/personality.py:411-415`），trait 越界静默 clamp（`models/personality.py:40-43`） |

---

## 2. 问题清单（按严重度排序）

### P0-1 运行中的会话会静默覆盖手工编辑

人格文件同时是「人设定义」和「情绪状态」的载体，运行时持有内存副本，到点**整文件**写回（`core/personality.py:134-144` 的 `save()` 写 `self.to_dict()` = personality + emotional_state 全量）。Web 端每条消息处理后都会触发防抖保存（`web/session.py:114-125`）。后果：

- 服务运行中手改 `personalities/小星.json` 的 `speaking_style`，最多 30 秒后被运行会话的内存状态整体覆盖，编辑丢失，**无任何提示**
- 人格编辑事实上的安全窗口是「停服 → 改 → 启动」，但这个约束没有任何文档写明（`doc/personality-guide.md:9` 只说「编辑对应角色文件后重启即可生效」，未警告运行中改会被覆盖）

### P0-2 `.bak` 备份时机错误，坏文件先污染备份再触发静默回退

`core/personality.py:105-109`：每次 load **先把当前文件复制成 `.bak`，然后再读**。正确的备份时机是「写入前」（保住即将被覆盖的版本），现在却是「读取前」。后果链：

1. 手改引入语法错误
2. 下次 load：坏文件被复制成 `.bak` → `json.load` 失败 → 静默回退 `PersonalityConfig()` 默认（Luna，`core/personality.py:112-114`）
3. 下次 save：Luna 默认整体覆盖原文件

备份里也是坏文件，情绪历史全丢——PE-004 想解决的「JSON 损坏 → 完全重置为默认 → 情绪历史全部丢失」（`changes/2026-06-01-comprehensive-fix-plan.md:368`）**并没有被解决**，只是多了一个同样损坏的副本。`tests/test_personality_core.py:92-98` 还把「损坏 → 静默回退默认」固化成了预期行为。

附带的整洁问题：`.bak` 每次 load 重写（内容≈当前文件镜像，无版本深度）；`personalities/*.bak` 未被 `.gitignore` 忽略（3 个 untracked 污染 git status），根目录 `personality.json.bak` 反而被提交进了 git。

### P0-3 无校验：拼错的字段名/特质名静默失效

- 特质名是自由文本，但情绪引擎只认硬编码的 6 个名字（`core/personality.py:48-72`：empathy / playfulness / warmth / thoughtfulness / humor / sass），prompt 特殊段落也只认 humor / sass（`prompts/system.py:370-374`）。写成 `playful` 不报错不警告，只是永远不生效
- `PersonalityConfig.from_dict()` 静默丢弃未知字段（`models/personality.py:415`）——`speaking_style` 拼成 `speak_style`，人设悄悄变空
- JSON 损坏与文件不存在走同一条回退路（`core/personality.py:101-114`），日志仅 warning——角色悄悄变成 Luna，用户从对话里才能察觉

### P1-1 模板即运行时：新角色继承别人的情绪包袱

`_ensure_personality_file()`（`web/session.py:144-148`）整文件复制模板，而模板 `personalities/default.json` 是 default 角色的**活文件**，内含真实积累的情绪状态（valence 0.88、trust 0.85）和 20 条情绪事件（"我是谁"、"woo" 等，`personalities/default.json:28-84`）。后果：每个新建角色带着 default 角色的情绪状态和情绪事件记忆出生。`doc/personality-guide.md:243` 让用户「可选：删除 `emotional_state`」——靠人肉记得做。

### P1-2 风格示例全局化，与人格文件脱节

`conversation_examples` 在全局 Config（`config.py:83-119`），默认值是小星专属口吻（蛙趣/旺柴/捂脸），无差别注入所有角色的 prompt。后果：

- 小明 / Luna / 未来任何角色的 prompt 里都注入小星风格的示例，人设被示例反向带偏
- 人格内容的一部分（风格示例）游离在人格文件之外，违反「状态唯一」原则（见 `../enhancement-overview.md` 第 2 节）

### P2-1 人格内容无演化通道、无版本钩子

- 人格自创建后永不变化：traits 不漂移、interests 不更新、backstory 不生长。自我系统对人格的定位是「几乎不变」（`../self-system.md` 第 3 节），这**不变**；但验收标准里的「成长性：经历会改变它——分寸感变好、口味形成」（`../self-system.md` 第 8 节）目前完全由记忆系统承担，人格层没有任何最小演化通道
- 人格文件无 `version` 字段，Layer 6 计划的格式迁移（`{id, config, emotional_state}`，见 `../layer6-personality/README.md` 数据模型一节）没有迁移钩子

---

## 3. 增强方案

### P0：安全地基（无依赖，可立即做）

**1. 合并保存：人格定义以磁盘为准，情绪以运行时为准**

`save()` 写回前先重读磁盘文件：磁盘的 `personality` 段 + 运行时的 `emotional_state` 段，合并后原子写回（保留 #153/#206 的原子写）。两个写者改的是不同字段（人改人设、引擎写情绪），合并是确定性逻辑，不需要锁。磁盘文件损坏时跳过本次保存并 error 日志，不覆盖、不毁证。

一并解决 P0-1（手改不再被覆盖，prompt 缓存本来就按文件 mtime 失效，改动随下次保存生效）和 P0-2 的覆盖环节。

**2. 备份改到写入前，加载错误分级**

- 备份时机从 load 前移到 save 前：`.bak` = 「即将被覆盖的磁盘版本」，配合合并保存，它总是最后一个已知良好版本
- load 分级：文件不存在 → 默认配置（正常新建路径，info）；文件存在但损坏 → 默认配置启动 + error 日志 + **只读保护**（该实例 `save()` 跳过并 warning），用户修复文件前运行时不会把默认值写回去毁证

**3. `.gitignore` 增加 `personalities/*.bak`**

根目录 `personality.json` 及已提交的 `.bak` 的退役归 Layer 6 Step 2（验收标准第 3 条），本文档不重复，只补 ignore 规则止住污染。

### P1：校验与模板（依赖 P0 的保存通道）

**4. 人格校验器**

`validate_personality(path) -> list[str]`，确定性检查：

- schema：必需字段、字段类型、`traits` 值域 [0,1]、`emotional_baseline` 键
- 特质名白名单：不在引擎使用名单内的特质 → warning「该特质仅作为 prompt 文本，不影响情绪引擎」（白名单 = `core/personality.py:48-72` 实际使用的名字；允许自由扩展，但效果要说清）
- 未知字段 → warning 列出（拼写错误的兜底网）

两个入口：`Personality.load()` 时运行，warning 全量打日志（**不拒绝加载**，灰度可回退）；独立 CLI（`python -m core.personality validate personalities/小星.json`）供编辑后主动检查。

**5. 模板纯净**

`_ensure_personality_file()` 复制模板后剔除 `emotional_state`，让 baseline 重建（`web/session.py:139-152`，一处改动）。校验器顺带把「模板文件含情绪事件」列为可检查项。

**6. 风格示例下沉到人格文件**

人格文件支持可选 `conversation_examples` 键：有则用角色的，无则回退全局 `config.conversation_examples`（双轨，可回退，不动 prompt block 结构，只改 `_build_examples_block` 的数据来源）。`config.py` 里的小星味默认示例逐步迁移进 `personalities/小星.json`，全局默认值收敛为空。

### P2：最小演化通道（默认关闭；依赖睡眠工作层）

**7. 人格演化提案**

配置开关 `personality_evolution_enabled`，**默认 false**。开启后，睡眠循环提炼阶段（见 `../layer1-memory/sleep-cycle.md`）追加一步「人格反思」：读近期 insights / experiences，产出提案追加写入 `personalities/{role}.evolution.jsonl`——万物有生命周期：`pending → applied / rejected / expired`。

- 可自动应用的仅限：`traits` 微调（单次 ≤ ±0.05，clamp [0,1]）、`interests` 增删
- `backstory` / `speaking_style` 永不自动改，只能以提案形式等人确认
- 应用走「校验器 + 合并保存」同一通道，不发明第二条写入路径

人格「几乎不变」的定位不变——这是一个人可观测、可拒绝、可回退的最小口子，不是人格自由漂移。

**8. 文件格式版本号**

人格文件加 `version` 字段，校验器按版本解析，为 Layer 6 的格式迁移留钩子。依赖 Layer 6 Step 2 的格式定稿。

---

## 4. 与现有设计的关系

- **自我系统（`../self-system.md`）**：人格 = 「稳定的我是谁、几乎不变」的定位不变；演化走睡眠循环这个「所有内部工作的统一调度窗口」，是内化拍的一部分；示例下沉后人格相关内容收拢进角色文件，符合「状态唯一」
- **Layer 6（`../layer6-personality/README.md`）**：根目录 `personality.json` 废弃、`PersonalityManager`、RoleSession 归 Layer 6。本文档的校验器与合并保存是 `PersonalityManager` 的天然内部能力，先在 `core/personality.py` 落地，Layer 6 实施时收编；根目录文件清理以 Layer 6 验收标准第 3 条为准
- **Layer 2（`../layer2-prompt/README.md`）**：不动 block 结构与缓存键，只改 identity / examples block 的数据来源；文件 mtime 版本机制（`core/prompt_cache.py:33-43`）已保证编辑后 prompt 自动重建
- **睡眠循环（`../layer1-memory/sleep-cycle.md`）**：P2 演化提案是睡眠流水线的一个可选 Stage，排在做梦之前（提案需要提炼完的 insights 作素材）
- **用户文档（`doc/personality-guide.md`）**：P0 落地后需更新——「运行中编辑会被合并保留」替代「重启生效」说法，并补校验器用法（本文档不改它，标注跟进）

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `core/personality.py` | 合并保存、备份移到写入前、load 错误分级 + 只读保护、校验入口、validate CLI | P0/P1 |
| `models/personality.py` | `validate_personality()`、可选 `conversation_examples` 字段、`version` 字段 | P1/P2 |
| `web/session.py` | 模板复制剔除 `emotional_state` | P1 |
| `prompts/system.py` / `core/message_handler.py` | examples block 数据来源：角色文件优先、全局回退 | P1 |
| `.gitignore` | `personalities/*.bak` | P0 |
| `config.py` | `personality_evolution_enabled` 开关；默认示例收敛 | P1/P2 |
| 睡眠循环工作层（未来文件） | 人格反思 Stage + evolution.jsonl 生命周期 | P2 |
| `tests/test_personality_core.py` 等 | 新增/修正覆盖（含改掉「损坏即静默回退」的旧预期） | 各期 |

---

## 6. 测试与验收

测试：

1. 运行中外部修改人格文件 → save 后外部修改仍在（合并而非覆盖），`emotional_state` 是运行时最新
2. 磁盘文件损坏时 save → 跳过 + error 日志，坏文件不被覆盖
3. save 成功后 `.bak` = 写入前的磁盘版本
4. 损坏 JSON 加载 → 默认配置启动、error 日志、实例只读（save 不生效）；文件不存在 → 默认配置、无 error
5. 校验器：拼错字段名 / 未知特质名 / 越界值 → warning 具体列出；合法文件 → 零 warning
6. 新建角色 → `emotional_state` 由 baseline 重建，不含模板的情绪事件
7. 角色文件带 `conversation_examples` → prompt 用角色的；不带 → 回退全局
8. 演化开关关闭 → 无 evolution 文件产生；开启 → 提案只追加、trait 幅度 ≤ ±0.05、backstory 不被自动改

验收：

- 手改 JSON 不再需要停服：改动在下次保存后体现在 prompt，且永不丢失
- 坏 JSON 不再导致角色静默变 Luna、情绪历史不再被默认值覆盖
- 新建角色不再带着别人的情绪出生
- 全量测试不降级

---

## 7. 相关文档

- `../self-system.md` — 自我状态定位与睡眠循环窗口
- `../layer6-personality/README.md` — 角色绑定与根目录文件废弃（互补，不重复）
- `../layer2-prompt/README.md` — Prompt 分层缓存（本方案只改 block 数据来源）
- `../layer1-memory/sleep-cycle.md` — P2 演化提案的宿主
- `../layer5-tool/enhancement-plan.md` — 本文档的结构模板
- `doc/personality-guide.md` — 用户向字段文档（P0 后需跟进更新）
- `changes/2026-06-01-comprehensive-fix-plan.md` — PE-004 原始问题记录
