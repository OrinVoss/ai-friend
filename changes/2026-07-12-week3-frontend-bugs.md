# Week 3 前端 bug 修复 + dispatcher 导入优化

## 修改文件

### web/static/app.js
- **FJ-007**: 头像文字"星"改为从 `init_ok.name` 动态获取，换人格自动更新
- **FJ-009**: REST 回退添加 `AbortController` 15s 超时，不再永久等待
- **FJ-002**: JSON.parse 空 catch 添加 `console.error`，调试可见
- **loadHistory()**: 添加 AbortController 15s 超时

### web/static/index.html
- **FH-003**: 标题"小星 - AI 朋友"改为"AI 朋友"，由 JS 动态更新
- **FH-002**: 添加 `<meta referrer="no-referrer">`

### web/server.py
- `init_ok` 响应添加 `name` 字段，前端据此更新头像和标题

### core/dispatcher.py
- `from core.async_utils import run_async` 从函数内移到模块顶部

### prompts/system.py
- **Fix #229**: emotion_behavior 查找改用 `emotion.dominant_emotion`（英文 key），修复全部 15 种情绪行为描述未生效的 bug
- `"fearful"` 统一为 `"afraid"`
