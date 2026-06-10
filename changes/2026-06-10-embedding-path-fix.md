# 2026-06-10 — 修复嵌入服务器启动失败（中文路径）

## 修改文件

- **main.py** — `_auto_start_embedding()` 改用 `start_embedding_server.bat` 相对路径避免中文路径编码问题；等待超时 10s→30s
- **web_main.py** — 同上

## 根因

`subprocess.Popen([llama_server, "-m", model])` 传入带中文的绝对路径 `D:\桌面\编程作品\AI朋友\memory\Qwen3.5-0.8B-Q6_K.gguf`。`llama-server.exe` 的 C++ `fopen` 无法识别该路径，模型加载失败，进程直接退出。

## 修复

改用 `.bat` 文件（相对路径 `memory\Qwen3.5-0.8B-Q6_K.gguf`）+ 设置 `cwd=project`。回退方案也使用相对路径。等待时间从 10s 延长到 30s（640MB 模型 + CUDA 初始化约 15-30s）。

## 效果

启动时自动拉起嵌入服务器，向量化检索可用。
