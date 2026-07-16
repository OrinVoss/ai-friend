# Memory Agent：线索提取规则

> 目标：把用户/Agent 的自然语言查询，拆解为结构化的 `MemoryClues`，供并行检索使用。

---

## 1. 线索类型

| 线索类型 | 说明 | 示例 |
|----------|------|------|
| `time_ranges` | 时间范围 | 今天、昨天、上周、2026-07-01 到 2026-07-14 |
| `entities` | 人名、地点、物品、事件 | 小星、外滩、Teeth、月光奏鸣曲 |
| `relationships` | 关系描述 | 我和用户、用户和女朋友、用户和老板 |
| `emotions` | 情绪标签 | 开心、难过、生气、焦虑、无聊 |
| `keywords` | 直接搜索词 | 火锅、披萨、编程、音乐 |
| `intent` | 查询意图 | recall / verify / compare / summarize |

---

## 2. 提取规则（一期：规则 + 正则）

### 2.1 时间线索

```python
TIME_PATTERNS = [
    (r"今天", ("today", "today")),
    (r"昨天", ("yesterday", "yesterday")),
    (r"前天", ("-2 days", "-2 days")),
    (r"上周|上星期", ("-7 days", "-1 days")),
    (r"这周|本周", ("monday this week", "today")),
    (r"上个月", ("-30 days", "-1 days")),
    (r"这个月|本月", ("-30 days", "today")),
    (r"(\d{4})年(\d{1,2})月", "custom"),
    (r"(\d{1,2})月(\d{1,2})日", "custom"),
]
```

一期只提取明确的相对时间词，不处理复杂自然语言时间。

### 2.2 实体线索

```python
ENTITY_PATTERNS = [
    # 人名（常见中文人名，2-3字）
    (r"[\u4e00-\u9fff]{2,3}", "person"),
    # 英文歌名/专辑名（首字母大写或全大写）
    (r"\b[A-Z][a-zA-Z0-9\s&'-]{2,30}\b", "entity"),
    # 地点（常见后缀）
    (r"[\u4e00-\u9fff]{2,10}(?:外滩|公园|公司|学校|医院|餐厅|电影院)", "location"),
]
```

注意：中文人名误报率高，一期只作为弱线索。

### 2.3 关系线索

```python
RELATIONSHIP_PATTERNS = [
    (r"我和(.+)", "user_and_other"),
    (r"(.+)和(.+)", "other_and_other"),
    (r"我(.+)你", "user_and_agent"),
    (r"你(.+)我", "agent_and_user"),
]
```

### 2.4 情绪线索

```python
EMOTION_KEYWORDS = {
    "joy": ["开心", "高兴", "快乐", "兴奋", "爽"],
    "sad": ["难过", "伤心", "沮丧", "低落", "郁闷"],
    "angry": ["生气", "愤怒", "气死", "烦", "讨厌"],
    "anxious": ["焦虑", "紧张", "担心", "害怕", "慌"],
    "bored": ["无聊", "没意思", "闲", "空虚"],
}
```

### 2.5 关键词线索

剩下的名词性词汇直接作为 keywords。可以用简单的停用词过滤：

```python
STOP_WORDS = {"的", "了", "在", "是", "我", "你", "他", "她", "它",
              "我们", "你们", "他们", "这", "那", "什么", "怎么", "为什么"}
```

### 2.6 意图判断

```python
INTENT_PATTERNS = [
    (r"还记得|记得吗|上次|之前", "recall"),
    (r"是不是|对吗|真的吗|确定吗", "verify"),
    (r"比较|对比|哪个更|区别", "compare"),
    (r"总结|概括|说说|讲讲", "summarize"),
]
```

---

## 3. 提取流程

```python
def extract_clues(query: str) -> MemoryClues:
    clues = MemoryClues(raw_query=query)
    
    # 1. 时间
    for pattern, time_range in TIME_PATTERNS:
        if re.search(pattern, query):
            clues.time_ranges.append(parse_time_range(time_range, query))
    
    # 2. 实体
    for pattern, entity_type in ENTITY_PATTERNS:
        for match in re.finditer(pattern, query):
            clues.entities.append(match.group(0))
    
    # 3. 关系
    for pattern, rel_type in RELATIONSHIP_PATTERNS:
        if re.search(pattern, query):
            clues.relationships.append(rel_type)
    
    # 4. 情绪
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(kw in query for kw in keywords):
            clues.emotions.append(emotion)
    
    # 5. 关键词
    words = tokenize(query)
    clues.keywords = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    
    # 6. 意图
    for pattern, intent in INTENT_PATTERNS:
        if re.search(pattern, query):
            clues.intent = intent
            break
    
    return clues
```

---

## 4. 二期：LLM 提取

当规则提取不足时，可以调用 LLM 做结构化提取：

```python
CLUE_EXTRACTION_PROMPT = """从下面这句话中提取记忆检索线索。

输出 JSON：
{
  "time_ranges": [["2026-07-01", "2026-07-14"]],
  "entities": ["Teeth", "外滩"],
  "relationships": ["user_and_agent"],
  "emotions": ["joy"],
  "keywords": ["音乐", "照片"],
  "intent": "recall"
}

只输出 JSON，不要其他内容。

查询：{query}
"""
```

使用 `response_format={"type": "json_object"}` 约束输出。

---

## 5. 测试用例

| 输入 | 期望提取结果 |
|------|-------------|
| 「我们上次聊了什么」 | intent=recall, time_ranges=[最近], keywords=[] |
| 「我最喜欢吃什么」 | intent=recall, keywords=["喜欢", "吃"] |
| 「Teeth 是谁唱的」 | intent=recall, entities=["Teeth"], keywords=["唱"] |
| 「我昨天不开心」 | intent=recall, time_ranges=[昨天], emotions=["sad"] |
| 「我和女朋友吵架了」 | intent=recall, relationships=["user_and_other"], emotions=["angry"] |
| 「2026年7月我们去哪了」 | intent=recall, time_ranges=[2026-07-01, 2026-07-31] |
