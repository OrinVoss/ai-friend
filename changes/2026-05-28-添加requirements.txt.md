# 添加 requirements.txt

**时间**：2026-05-28

## 修改文件

- `requirements.txt` — 新增，锁定项目依赖版本

## 修改原因

Fix #39：项目缺少依赖声明文件，通过 README 手动 pip install 管理，无版本锁定。

## 修改内容

锁定 5 个依赖及版本：
- requests 2.34.2
- tiktoken 0.13.0
- plyer 2.1.0
- fastapi 0.111.0
- uvicorn 0.30.1
