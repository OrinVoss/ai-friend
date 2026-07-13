# 移动端状态面板从右侧滑入

## 问题
移动端点击底部「状态」tab 时，状态面板从左侧滑入；而点击「日志」时，日志面板从右侧滑入。两者动画方向不一致，体验别扭。

## 改动
- `web/static/style.css`
  - 在 `@media (max-width: 900px)` 下，将 `.status-panel` 改为从右侧滑入：
    - `right: 0; left: auto;`
    - `transform: translateX(100%)`
    - `.status-panel.open { transform: translateX(0) }`
  - 统一 `.status-panel` 与 `.logs-panel` 的边框方向。
- `web/static/index.html`
  - 静态资源缓存版本号从 `?v=7` 提升到 `?v=8`。

## 效果
移动端状态面板和日志面板都从屏幕右侧滑入，动画方向一致。

## 验证
- 在浏览器开发者工具中切换到移动端视口（宽度 <= 900px）。
- 点击底部「状态」tab，确认面板从右向左滑入。
- 点击底部「日志」tab，确认面板同样从右向左滑入。
