# 178 Issue 一月修复计划

> 状态：**第1-2周全部完成 ✅** | P0: 6/6 | P1: 45/45 | 测试 288 passed + 2 skipped

## 总览

| 周 | 重点 | 状态 | P0/P1 closed |
|----|------|------|-------------|
| [第1周](week-1-hemostasis.md) | P0 + 安全关键 | ✅ 全部完成 | 9 issues closed |
| [第2周](week-2-stabilization.md) | 核心可靠 | ✅ 全部完成 | 45 issues closed |
| [第3周](week-3-completion.md) | 质量补全 | 待开始 | — |
| [第4周](week-4-finalize.md) | 收尾加固 | 待开始 | — |

## 已完成（第1周 P0）

| # | 问题 | commit |
|---|------|--------|
| #193 | store_fact 重复定义 | c032226 |
| #201 | repo 缺少 commit() 9 个方法 | c032226 |
| #203 | Agent 1 registry 隔离 | c4cc233 |
| #204 | round_number 递增 | c4cc233 |
| #205 | 多轮结果传递 | c4cc233 |
| #206 | save() 竞态 | c4cc233 |
| #207 | FactChecker.resolve 空操作 | c4cc233 |
| #240 | PowerShell 注入修复 | c032226 |
| #245 | turn_id 竞态 | c032226 |
| #264 | notify 异常日志 | c032226 |

## 已关闭（单人场景不适用）

| # | 原因 |
|---|------|
| #202 | 单人使用无跨 session 竞态 |

## 范围调整

**单人使用**意味着以下类 issue 不触发：
- 多 session 竞态（#202, #211 等）
- WebSocket Origin 绕过（localhost 单人）
- REST API 并发阻塞（单用户不影响）
- 多标签页 session 冲突

精简后有效 issue 约 100 个（原 178）。

