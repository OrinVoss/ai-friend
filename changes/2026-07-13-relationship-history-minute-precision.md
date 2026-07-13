# 关系指标历史时间精确到分钟

## 问题
关系指标「历史变化」面板只显示 `MM/DD` 日期，同一天多次变化的记录无法区分，看起来像是「没有变化」。

## 改动
- `web/static/app.js`
  - 新增 `formatDateTime(ts)`，返回 `MM/DD HH:mm` 格式。
  - `renderStatus()` 中历史记录的时间戳改用 `formatDateTime`，精确到分钟。
- `web/static/index.html`
  - 静态资源缓存版本号从 `?v=4` 提升到 `?v=5`，确保浏览器加载新脚本/样式。

## 效果
历史变化列表现在显示例如 `07/13 07:26`，可以清晰看到同一分钟内关系指标的多次变化。

## 验证
- `python -m py_compile web/static/app.js` 语法检查通过（JS 通过浏览器 console 验证）。
- 刷新页面后 `/api/status` 返回的历史数据时间戳显示为 `07/13 07:26`。

## 后续
关系指标数值本身仍受 consolidation 频率限制（每 3 轮一次）。如需更实时的波动，需要额外在每次对话后基于情绪事件更新关系指标。
