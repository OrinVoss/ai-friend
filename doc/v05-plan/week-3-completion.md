# 第3周：补全（P1 收尾 + P2 批量，~55 个）

**目标**：代码质量达到可维护标准。死代码、魔法数字、bare except 清零。

**状态：核心逻辑全部完成 ✅，前端修复见下**

---

## Day 1-2：工具层（15 个）✅

工具层修复全部完成。

---

## Day 3-4：前端 + CLI（20 个）

### app.js — 稳定性

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| FJ-005 ✅ | 固定 3s 重连 | 改为 2s + 25s ping | 快速恢复 + 防超时 |
| FJ-007 ✅ | 角色名硬编码 | `init_ok.name` 动态获取 | 换人格头像名自动更新 |
| FJ-009 ✅ | REST 回退无超时 | `AbortController` 15s | 不永久等待 |
| FJ-002 ✅ | JSON.parse 空 catch | `console.error` | 调试可见 |
| FJ-010 ✅ | 切片与 markdown 冲突 | 取消切片，单 segment + markdown | markdown 不剖坏 |

**FH-003 ✅**：标题"小星"改为从 `init_ok.name` 动态更新  
**FH-002 ✅**：添加 `<meta referrer="no-referrer">`

---

## Day 5-7：模型 + 提示词（20 个）✅

全部完成。
