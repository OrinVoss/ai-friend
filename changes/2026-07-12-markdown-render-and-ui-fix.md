# Markdown 渲染 + UI 优化 + 嵌入进程去重

## 修改文件

### web/static/index.html
- 引入 `marked.min.js`（本地，不依赖 CDN）
- `app.js?v=2` 防缓存

### web/static/app.js
- **Markdown 渲染**：`createMessage()` 中 assistant 气泡使用 `marked.parse()` 渲染
- **流式分段保护**：segment 期间用 `data-raw` 累积原文，仅显示纯文本；`done` 时整体渲染 markdown，避免分段剖坏格式
- **历史加载受益**：`loadHistory()` 走 `createMessage()`，历史气泡也支持 markdown

### web/static/marked.min.js
- 新增：marked 库（39KB），本地静态文件

### web/static/style.css
- 气泡内布局控制：`overflow: hidden`→移除（避免裁掉列表序号）
- `<ol>/<ul>` padding-left 20px→32px，序号不贴边
- `pre` 代码块 margin 撑满气泡宽度
- 行内代码 `word-break`、图片 `max-width: 100%`、链接颜色
- 标题、引用、分割线样式

### web_main.py / main.py
- 新增 `_kill_existing_llama()`：启动嵌入服务前先杀旧 llama-server 进程，防止每次重启都多一个
