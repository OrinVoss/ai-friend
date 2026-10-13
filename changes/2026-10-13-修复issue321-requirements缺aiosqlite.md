# 修复 issue #321：requirements.txt 补全直接依赖 aiosqlite / pydantic

## 修改的文件
- `requirements.txt`

## 修改原因
`storage/database.py` 直接 `import aiosqlite`，但 requirements.txt 未声明，全新环境 `pip install -r requirements.txt` 后启动必然 ImportError。pydantic 在 `web/schemas.py` 直接使用，此前仅靠 fastapi 传递依赖覆盖，一并显式声明。

## 修改内容
- requirements.txt 增加 `aiosqlite==0.22.1`、`pydantic==2.13.4`（与当前开发环境版本一致）。
