# 彻底收起桌面端面板

## 问题

桌面端点击收起后，面板只是被压缩成窄条，`.panel-body` 内容仍然竖排可见（如"关系指标"、"历史变化"），形成"收起来了，又没有完全收起来"的效果。

## 改动

- `web/static/index.html`
  - 将 `.panel-expand` 从 `.side-panel` 内部移除，改为 `.app-main` 内独立的 `.panel-expand-bar` 按钮（`.status-expand` 和 `.logs-expand`）。
  - 这样面板本身可以真正 `display: none`，展开条独立存在。
  - 静态资源版本号提升到 `?v=13`。

- `web/static/style.css`
  - `.panel-expand` 相关样式替换为 `.panel-expand-bar`。
  - 桌面端 `.side-panel.collapsed` 恢复为 `display: none`，面板完全隐藏。
  - 使用相邻兄弟选择器显示对应的展开条：
    - `.side-panel.status-panel.collapsed + .status-expand`
    - `.side-panel.logs-panel.collapsed ~ .logs-expand`

- `web/static/app.js`
  - 将 `.panel-expand` 点击监听改为 `.panel-expand-bar`。

## 验证

- 桌面端点击 header 收起箭头后，面板完全消失，只在边缘留下一小块展开按钮。
- 点击展开按钮可恢复面板。
- 移动端不受影响。
