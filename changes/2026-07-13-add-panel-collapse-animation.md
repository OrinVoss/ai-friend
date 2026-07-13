# 桌面端面板展开收起动画

## 问题

桌面端面板收起/展开是瞬间切换，没有过渡动画，体验生硬。

## 改动

- `web/static/index.html`
  - 静态资源版本号提升到 `?v=14`。

- `web/static/style.css`
  - `.side-panel` 增加 `overflow: hidden`，并过渡 `width`、`opacity`、`transform` 三个属性。
  - 桌面端 `.side-panel.collapsed` 不再 `display: none`，而是变为 `width: 0`、`opacity: 0`，并配合 `transform: translateX(-100%)`（左侧面板）/ `translateX(100%)`（右侧面板）滑出屏幕。
  - `.panel-expand-bar` 默认 `opacity: 0`、`pointer-events: none` 并过渡 `opacity`；对应面板 collapsed 时淡入显示。

- `web/static/app.js`
  - 无需改动，`togglePanel()` 继续切换 `.collapsed` 类即可驱动动画。

## 验证

- 桌面端点击 header 收起箭头：面板宽度平滑收缩、透明度淡出、并向左/右滑出，中间聊天区同步扩展。
- 点击边缘展开条：面板反向滑入并展开。
- 移动端仍使用 `transform: translateX()` 滑入滑出，不受影响。
