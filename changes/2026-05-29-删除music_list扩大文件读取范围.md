# 删除 music_list，扩大文件读取范围

**时间**：2026-05-29

## 修改文件

- `tools/file_tools.py` — read_file 允许读取多个目录（项目/D:\音乐/D:\桌面/Documents/Downloads）
- `tools/music_tool.py` — 保留 music_play，删除 music_list
- `main.py` / `web/session.py` — 移除 MusicListTool 注册

## 原因

glob + read_file 已覆盖 music_list 的功能，无需重复。扩大 read_file 白名单目录，覆盖常用文件位置。

## 当前工具：9 个

read_file / glob / grep / recall / remember / notify / web_search / web_fetch / music_play
