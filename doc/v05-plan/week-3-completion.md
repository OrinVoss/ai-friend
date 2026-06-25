# 第3周：补全（P1 收尾 + P2 批量，~55 个）

**目标**：代码质量达到可维护标准。死代码、魔法数字、bare except 清零。

**状态：Day 1-2 工具层 15/15 ✅**

---

## Day 1-2：工具层（15 个）

### file_tools — 路径安全 + 性能

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| FL-001 ✅ | `logger.debug` 引用未定义变量 `path` | 改为 `filepath` | NameError 修复 |
| FL-002 ✅ | `_get_allowed_roots` 每次检查都读文件 | 缓存 60s | 性能提升 |
| FL-005 ✅ | 目录列表暴露隐藏文件 | 过滤 `.*` 开头文件 | 安全性 |
| FL-007 ✅ | `f.readlines()` 全量加载 | `itertools.islice(f, limit)` | 大文件不 OOM |

### search_tools — 代码清理

| ID | 问题 | 修复 |
|----|------|------|
| SR-003 ✅ | `os.walk` 无文件计数上限 | 超过 10000 文件停止 |
| SR-004 ✅ | 死代码 `pass` + 重复条件 | 删除 |
| SR-007 ✅ | `"data" in dirpath` 子字符串误杀 | `os.sep` 分割精确匹配 |
| SR-008 ✅ | `errors="ignore"` 二进制文件误导 | 先 `_is_binary()` 检查 |
| SR-009 ✅ | 魔法数字无注释 | 命名常量 `MAX_RESULTS` |

### music_tool — 安全

| ID | 问题 | 修复 |
|----|------|------|
| MU-002 ✅ | 遍历无上限 | 停止 10000 文件后 |
| MU-004 ✅ | `os.startfile` 执行任意类型 | realpath 后 verify 扩展名 `.mp3/.wav/.flac` |

### web_tools — HTTP 优化

| ID | 问题 | 修复 |
|----|------|------|
| WT-001 ✅ | 每次新建 Session | 模块级单例 `_session` |
| WT-002 ✅ | JSON-RPC id 固定 | `uuid.uuid4().hex` |
| WT-003 ✅ | 无重试 | 指数退避 3 次 |
| WT-004 ✅ | freshness 不校验 | 校验 enum，无效时忽略 |

---

## Day 3-4：前端 + CLI（20 个）

### app.js — 稳定性

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| FJ-005 | 固定 3s 重连 | 指数退避 3s→6s→12s→24s，最大 10 次 | 不风暴 |
| FJ-008 | 心跳重连时翻倍 | 新连接前 `clearInterval` | CPU 不泄漏 |
| FJ-007 | 角色名硬编码 | `fetch('/api/name')` 从后端获取 | 动态角色名 |
| FJ-009 | REST 回退无超时 | `AbortController` 15s 超时 | 不永久等待 |
| FJ-002 | JSON.parse 空 catch | 添加 `console.error` | 调试可见 |
| FJ-010 | splitSegments 与后端不同步 | 移除前端分段，后端 `_send_segments` 统一 | 行为一致 |

**⚠ 风险**：移除前端分段后，所有消息由后端推送控制。需确认延迟公式在前端仍然合理。

### index.html + style.css

| ID | 问题 | 修复 |
|----|------|------|
| FH-001 | 无 CSP meta | `<meta http-equiv="Content-Security-Policy" content="...">` |
| FH-002 | 无 referrer | `<meta name="referrer" content="no-referrer">` |
| FH-003 | 标题"小星"硬编码 | 从 personality.name 动态生成 |
| FH-004 | textarea 无 aria-label | 添加 |
| FC-001 | 229 行颜色值散布 | 定义 `:root` CSS 变量 |

### display.py — CJK 修复

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| DP-002 | `len()` 计 CJK 为 1 列 | 用 `wcwidth` 库（或简单 CJK→2 估算） | 行宽正确 |
| DP-004 | CJK 无空格断句 | 在 CJK 字符间允许断点 | 不截断语义 |
| DP-010 | `\n` 双重延迟 | 从 sentence-ending 集合移除 `\n` | 速度正常 |

### cli.py — 配置生效

| ID | 问题 | 修复 |
|----|------|------|
| CL-001 | DisplayEngine 不接收 typing_speed | 从 config 传入 |

### config.py — 验证

| ID | 问题 | 修复 |
|----|------|------|
| CF-002 | 字段无验证 | `validate_config()` 检查范围 |
| CF-009 | 仅 5 个环境变量映射 | 补全所有 config 字段的环境变量 |
| CF-006 | Windows 硬编码路径 | 从默认值移除 `D:\音乐`、`D:\桌面` |

### main.py + web_main.py

| ID | 问题 | 修复 |
|----|------|------|
| MA-005 | `db.close()` 缺 await | `await db.close()` |
| MA-003 | temperature 不传给 provider | 传参 |
| MA-001 | 初始化无异常处理 | try/except + 友好错误消息 |

---

## Day 5-6：模型 + 提示词（20 个）

### models/memory.py

| ID | 问题 | 修复 |
|----|------|------|
| MM-001 | composite_score 语义混 | 添加 `runtime_score` 属性 |
| MM-002 | 缺范围验证 | `__post_init__` 检查 confidence/importance 范围 |
| MM-003 | fact_type 应 Literal | `Literal["user_fact", "agent_fact", "system_fact"]` |
| MM-004/005 | Experience/Reflection 缺枚举 | `EmotionalTone`、`InsightType` 枚举 |
| MM-006 | Reflection 缺 level/parent_ids | 添加字段（L1/L2/L3） |

### models/conversation.py

| ID | 问题 | 修复 |
|----|------|------|
| MC-001 | Turn.timestamp 非 JSON 序列化 | `to_dict()` 转 ISO 8601 |
| MC-002 | role 应 Literal | `Literal["user", "assistant"]` |
| MC-003 | relationship 硬编码默认值 | 改为空 dict |

### prompts/system.py

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| SY-002 | Agent 1 自然语言解析脆弱 | 切换到结构化 JSON 输出 | LLM 兼容性需验证 |
| SY-003 | 8 个对话示例 ~600 tokens | 前 2 次注入后移除，或移到配置 | token 节省 |
| SY-014 | **kwargs 隐藏参数 | 改为显式参数 `idle_duration`, `tool_call_history`, `explore_mode` | 函数签名清晰 |
| SY-012 | `tc["success"]` KeyError | 改为 `.get("success", False)` | 不崩溃 |

**⚠ 风险**：SY-002 切换 JSON 输出需要 Agent 1 prompt 重写，LLM 可能不遵循新格式。在第一周保守处理：保留自然语言回退。

### prompts/templates.py

| ID | 问题 | 修复 |
|----|------|------|
| TM-001 | .format() 无 try/except | try/except KeyError + 日志 |
| TM-005 | 情感分析 JSON 被 markdown 包裹 | `re.search(r'\{.*\}', result)` 提取 |
| TM-006 | 死导入 | 删除未使用的 MemoryContext 等 |

---

## Day 7：验证

- 全量测试
- 前端手动回归（主要功能路径）
- CLI 手动测试（typing_speed、CJK 换行）
- 提示词变更 LLM 输出验证

---

## 第3周风险总结

| 风险 | 等级 | 缓解 |
|------|------|------|
| FJ-010 移除前端分段破坏气泡体验 | 中 | 后端 _send_segments 独立测试 |
| SY-002 JSON 切换 LLM 不兼容 | 高 | 保留自然语言回退 |
| wcwidth 库引入新依赖 | 低 | 简单 CJK 判断替代 |
