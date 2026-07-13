# 桌面端面板展开条

## 问题

桌面端点击面板 header 的收起箭头后，`.side-panel` 会加上 `.collapsed` 类并被 `display: none` 隐藏，导致收起按钮也一起消失，用户无法在不刷新页面的情况下重新展开面板。

## 改动

- `web/static/index.html`
  - 修复左侧状态面板错误地用 `</section>` 关闭的 HTML 结构问题，改为正确的 `</aside>`。
  - 在左右两个面板的 `aside` 内部各增加一个 `.panel-expand` 展开按钮，使用 SVG 箭头图标。
  - 静态资源版本号提升到 `?v=12`。

- `web/static/style.css`
  - `.side-panel` 增加 `position: relative` 和 `width` 过渡动画。
  - 新增 `.panel-expand` 样式：桌面端面板收起时显示为 28px 宽的垂直圆角条，位于面板边缘，与整体浅色 UI 风格一致。
  - 桌面端 `.side-panel.collapsed` 不再 `display: none`，而是收缩为 28px 宽，仅显示展开条，隐藏面板 header 和 body。
  - 左侧面板展开条在右侧、箭头朝右；右侧面板展开条在左侧、箭头朝左。

- `web/static/app.js`
  - 为 `.panel-expand` 按钮添加点击监听，调用 `togglePanel()` 展开对应面板。

## 验证

- HTML 结构已修正，左右两个 `aside` 标签正确闭合。
- 桌面端（`>=901px`）默认两侧面板展开；点击 header 箭头收起后，边缘出现细窄展开条；点击展开条恢复面板。
- 移动端（`<=900px`）`.panel-expand` 始终隐藏，不影响底部 tab 切换逻辑。
