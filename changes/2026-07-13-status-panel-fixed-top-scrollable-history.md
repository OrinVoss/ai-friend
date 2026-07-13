# 状态面板：顶部固定，仅历史变化滚动

## 问题
左侧状态面板整体滚动时，「对话轮次」「当前情绪」「关系指标」会一起滚出视图。用户希望这些板块固定，只有「历史变化」可以滚动。

## 改动
- `web/static/style.css`
  - `#status-body` 改为 `display: flex; flex-direction: column; overflow-y: hidden`，让面板整体不再滚动。
  - 最后一个 `.status-section`（历史变化所在容器）设为 `flex: 1`，内部也使用 flex column 占满剩余高度。
  - `.history-list` 设为 `flex: 1; overflow-y: auto; min-height: 0`，只在该区域内滚动。
  - 为 `.history-list` 添加细细的自定义滚动条（4px 宽）。
- `web/static/index.html`
  - 静态资源缓存版本号从 `?v=9` 提升到 `?v=10`。

## 效果
桌面端和移动端打开状态面板时：
- 「对话轮次」「当前情绪」「关系指标」始终固定在顶部。
- 「历史变化」占满下方剩余空间，内容多时单独滚动，滚动条细窄。

## 验证
- 打开状态面板，确认顶部卡片和关系指标不随历史变化滚动。
- 历史变化条目足够多时，该区域出现细滚动条。
