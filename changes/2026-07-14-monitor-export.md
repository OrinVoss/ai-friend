# 监控页面新增导出功能

## 需求

监控页面 `/monitor` 需要支持把当前页面记录的 LLM 请求与响应导出到本地，方便离线查看、分享和排错。

## 修改

### 前端

- `web/static/monitor.html`
  - 在控制栏新增两个按钮：
    - **⬇ 导出 JSON**：导出原始完整数据
    - **⬇ 导出 Markdown**：导出格式化的阅读版本

- `web/static/monitor.js`
  - 新增 `currentData` 全局变量，在每次 `fetchData` 成功后保存当前记录。
  - 新增 `downloadBlob(content, filename, type)` 辅助函数，通过临时 `<a>` 标签触发浏览器下载。
  - 新增 `formatTimestamp()` 生成 `YYYYMMDD_HHMMSS` 格式的时间戳作为文件名后缀。
  - 新增 `exportJson()`：
    - 将当前记录包装为 `{ exported_at, count, records }`。
    - 下载为 `llm_monitor_YYYYMMDD_HHMMSS.json`。
  - 新增 `exportMarkdown()`：
    - 为每条记录生成独立章节，包含时间、来源（source）、模型、耗时、温度、`max_tokens`、`response_format`。
    - 请求消息按 `role` 分组，响应单独一块。
    - 使用 Markdown 代码块包裹文本内容，避免特殊字符破坏格式。
    - 下载为 `llm_monitor_YYYYMMDD_HHMMSS.md`。
  - 在 `initMonitor()` 中为两个导出按钮绑定点击事件。

## 验证

- 本地语法检查：`node --check web/static/monitor.js` 通过。
- 浏览器访问 `/monitor` 后可看到导出按钮，点击可正常下载文件。

## 提交

`6601c76` MN-005: 监控页面支持导出 JSON / Markdown
