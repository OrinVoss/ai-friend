# 修复 issue #341：repository JSON 列解析无容错

## 修改的文件
- `storage/repository.py`

## 修改原因
`_row_to_experience/_row_to_insight/_row_to_fact_v2` 的 `json.loads(tags/evidence_fact_ids/source_observation_ids)` 无容错，一行损坏 JSON 会让该 session 的所有相关查询抛 JSONDecodeError。

## 修改内容
- 新增 `_parse_json_list` 静态方法：坏数据记 warning 并按 [] 处理，非 list 结果也归一为 []。
- 三处 row 转换改用容错解析。
- 验证：`pytest -k "repository or storage"` 35 passed。
