# 桌面端面板收起按钮 + 移动端显示切换按钮

## 改动
- `web/static/index.html`
  - 桌面端 header-right 只保留「切换」按钮，移除「状态」「日志」两个 SVG 图标按钮。
  - 在左侧状态面板、右侧日志面板的 `panel-header` 内各添加一个桌面端专用的「收起」按钮（向左/向右箭头 SVG）。
  - 静态资源缓存版本号从 `?v=10` 提升到 `?v=11`。
- `web/static/style.css`
  - 新增 `.panel-collapse` 类，默认隐藏，桌面端（`min-width: 901px`）显示。
  - 桌面端隐藏 `.panel-close`，移动端隐藏 `.panel-collapse` 和 `.panel-close`。
  - 移除 `@media (max-width: 600px)` 里对 `.header-right` 的 `display: none`，使移动端顶部也显示「切换」按钮。
- `web/static/app.js`
  - 删除已不存在的 `logs-toggle`、`status-toggle` 的事件监听。
  - 为 `.panel-collapse` 按钮添加点击事件，调用 `togglePanel()` 收起对应面板。

## 效果
- 桌面端：右上角只有「切换」；左右面板默认展开；点击面板标题旁的箭头可收起对应面板。
- 移动端：顶部 header 显示「切换」按钮，底部 tab 保留聊天/状态/日志切换。

## 验证
- 桌面端确认 header 只剩「切换」，面板 header 有箭头按钮，点击后对应面板隐藏。
- 移动端确认顶部有「切换」按钮，底部 tab 正常。
