# 移动端与桌面端 tab 图标改用 SVG

## 问题
移动端底部 tab（聊天/状态/日志）和桌面端顶部切换按钮使用 emoji 图标（💬/📊/📝），在不同系统/字体下显示不一致，且不够精致。

## 改动
- `web/static/index.html`
  - 桌面端 `logs-toggle`、`status-toggle` 的 emoji 替换为内联 SVG 图标。
  - 移动端底部 `tab-btn` 的 emoji 替换为内联 SVG 图标 + `<span>` 文字，改为纵向排列。
- `web/static/style.css`
  - `.icon-btn` 移除 `font-size`，统一使用 20×20 SVG，并继承当前文字颜色。
  - `.tab-btn` 改为 `flex-direction: column`，图标在上文字在下，间距 2px。
  - 静态资源缓存版本号从 `?v=8` 提升到 `?v=9`。

## 效果
移动端和桌面端的聊天、状态、日志入口都使用一致的 SVG 线框图标，不再依赖系统 emoji 字体。

## 验证
- 在桌面浏览器确认顶部「状态」「日志」按钮显示为 SVG 图标。
- 在移动端视口确认底部 tab 显示 SVG 图标 + 文字。
