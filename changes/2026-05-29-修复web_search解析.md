# 修复 web_search 结果解析

**时间**：2026-05-29

## 修改文件

- `tools/web_tools.py` — 修复 AnySearch 返回结果的解析逻辑

## 问题

AnySearch API 返回格式为 `{"content": [{"type": "text", "text": "markdown..."}]}`，之前的解析把它当成了结构化对象数组（有 title/snippet/url 字段），导致结果始终为空。

## 修复

直接提取 `content[0].text` 的 markdown 文本返回。
