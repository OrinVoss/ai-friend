# AI Friend 项目规则

## 修改记录

每次修改本项目文件时，必须在 `changes/` 目录下创建修改记录文件。

- 文件命名格式：`YYYY-MM-DD-简短描述.md`
- 记录内容：修改的文件、修改原因、修改内容摘要

## 项目路径

D:\桌面\编程作品\AI朋友

## 关键命令

- `python main.py` — CLI 模式启动
- `python web_main.py` — Web 模式启动（http://localhost:8000）
- 提交前运行 `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py` 检查语法

## Bug 修复流程

- 发现 bug 后**先创建 GitHub issue**，再修复代码
- Issue 需包含：现象描述、根因分析、修复方案
- 修复 commit message 引用 issue 编号（如 `Fix #59: ...`）
- 修复后更新 changes/ 修改记录

## 文档规范

- 写技术文档时善于使用 ASCII 图（流程图、状态机、架构图、数据流图）来表达
- 更新代码的同时更新对应的 doc、README、changes
