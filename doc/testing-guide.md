# 测试指南

> 如何运行和编写 AI Friend 的测试。

---

## 运行测试

### 运行所有测试

```bash
# 项目根目录
python -m pytest tests/ -v
```

### 按文件运行

```bash
# 只运行某个测试文件
python -m pytest tests/test_agent.py -v

# 运行某个测试类
python -m pytest tests/test_personality_core.py -v
```

### 运行真实 API 测试

部分测试需要真实的 DeepSeek API Key，默认跳过：

```bash
# 需要在环境变量中设置 DEEPSEEK_API_KEY
set DEEPSEEK_API_KEY=sk-your-key-here

# 运行包含真实 API 调用的测试
python -m pytest tests/ tests/real_api/ -v --real-api
```

### 运行语法检查

```bash
python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py ui/*.py
```

---

## 测试架构

```
tests/
├── conftest.py              # pytest 配置，--real-api 选项
├── mocks.py                 # 共享 mock 对象
│
├── test_agent.py            # Agent 核心逻辑测试
├── test_agent_proactive.py  # 主动行为测试
├── test_message_handler.py  # 消息处理测试
├── test_cli_controller.py   # CLI 状态机测试
│
├── test_personality_core.py # 情绪引擎核心测试
├── test_emotional_state.py  # EmotionalState 数据模型测试
│
├── test_inner_drive.py      # Agent 1 InnerDrive 测试
├── test_tool_agent.py       # Agent 2 ToolAgent 测试
├── test_dispatcher.py       # 工具调用解析测试
├── test_memory_tools.py     # recall/remember 测试
│
├── test_provider.py         # LLM API 客户端测试
├── test_retrieval.py        # 记忆检索测试
├── test_consolidation.py    # 记忆合并测试
├── test_repository.py       # 数据访问层测试
│
├── test_context_manager.py  # 上下文管理测试
├── test_sleep_manager.py    # 睡眠管理测试
├── test_fact_checker.py     # FactChecker 测试
├── test_segmentation.py     # 分段推送测试
├── test_web_agent.py        # WebAgent 测试
├── test_provider_abc.py     # LLMProvider ABC 测试（#23）
├── test_rate_limit.py       # 速率限制测试（#24）
├── test_conversation_examples.py  # 对话示例可配置测试（#28）
│
├── test_v02_issues.py       # v0.2 issue 回归测试
│
├── test_conversation.py     # 对话模型测试
│
├── real_api/                 # 需要真实 API 的集成测试
│   ├── conftest.py
│   ├── test_provider.py
│   ├── test_inner_drive.py
│   ├── test_react_loop.py
│   └── test_dream.py
```

---

## Mock 策略

`tests/mocks.py` 提供了以下 mock：

### MockProvider

模拟 LLM API 返回，不发起真实 HTTP 请求：

```python
from tests.mocks import MockProvider

# 默认返回 "Mock response"
provider = MockProvider()

# 自定义返回
provider = MockProvider(response="你好呀！")

# JSON 模式返回
provider = MockProvider(json_mode=True, response='{"sentiment": 0.5}')
```

### MockLongTermMemory & MockRepository

模拟数据库操作的内存实现：

```python
from tests.mocks import MockLongTermMemory, MockRepository

repo = MockRepository()
ltm = MockLongTermMemory(repo)
ltm.store_fact("preference", "color", "blue", 0.9)
facts = ltm.get_all_active_facts()  # 内存操作，不涉及 SQLite
```

### MockEmbeddingEngine

模拟嵌入向量生成：

```python
from tests.mocks import MockEmbeddingEngine

embed = MockEmbeddingEngine(dim=512)
vec = embed.encode_single("hello")  # 返回随机向量
```

### 断言辅助

```python
# 验证工具调用记录
assert len(agent._tool_call_history) > 0
assert agent._tool_call_history[-1]["name"] == "recall"
assert agent._tool_call_history[-1]["success"] is True
```

---

## 编写测试

### 标准结构

```python
import pytest
from tests.mocks import MockProvider, MockLongTermMemory

def test_something():
    # Arrange
    provider = MockProvider(response="Hello!")
    ltm = MockLongTermMemory(MockRepository())
    
    # Act
    result = some_function(provider, ltm)
    
    # Assert
    assert result == "expected"
```

### 测试情绪引擎

```python
def test_emotion_shift():
    from models.personality import EmotionalState
    
    e = EmotionalState()
    e.shift(delta_v=0.3, delta_a=0.2, primary_deltas={"joy": 0.2})
    
    assert e.valence > 0.4
    assert e.arousal > 0.3
    assert e.joy > 0.5
```

### 真实 API 测试标记

```python
import pytest

class TestRealAPI:
    def test_basic_chat(self):
        # 这个测试始终运行
        pass
    
    @pytest.mark.real_api
    def test_with_real_llm(self):
        # 只在 --real-api 标志下运行
        pass
```

### 新增功能测试要点

**Provider ABC（#23）**：验证自定义 Provider 必须实现 `generate` 方法，且 `KimiProvider` 是 `LLMProvider` 子类。

```python
from core.provider import LLMProvider, KimiProvider

assert issubclass(KimiProvider, LLMProvider)
```

**速率限制（#24）**：验证 `RateLimiter` 在 60 秒窗口内对同一 IP 限制 30 次 `/api/chat`。

```python
from web.rate_limit import RateLimiter

limiter = RateLimiter()
for _ in range(30):
    assert limiter.check("127.0.0.1", "/api/chat")
assert not limiter.check("127.0.0.1", "/api/chat")
```

**Pydantic 校验（#43）**：验证 `ChatRequest` 对空 `message` 返回 422。

```python
from web.schemas import ChatRequest
from pydantic import ValidationError

with pytest.raises(ValidationError):
    ChatRequest(message="")
```

**WebAgent 封装（#45）**：验证 `WebAgent` 暴露 `emotion`、`turn_count`、`process_message` 等公共接口，Web 端不直接访问 `agent._xxx`。

**对话示例可配置（#28）**：验证 `build_system_prompt` 传入不同 `conversation_examples` 后 prompt 包含对应示例文本。

---

## 调试技巧

### 只看失败的测试

```bash
python -m pytest tests/ -v --tb=short  | findstr FAILED
```

### 打印详细日志

```bash
python -m pytest tests/ -v -s --log-cli-level=DEBUG
```

### 跳过慢测试

```bash
python -m pytest tests/ -v -k "not slow"
```

### 代码覆盖率

```bash
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=term-missing
```
