# 测试指南

> 如何运行和编写 AI Friend 的测试。

---

## 运行测试

### 运行所有测试

```bash
# 项目根目录（排除需要真实 API key 的 real_api/）
python -m pytest tests --ignore=tests/real_api -q
```

当前共 60+ 个测试文件、841 个用例（841 passed + 2 skipped）。

### 按文件运行

```bash
# 只运行某个测试文件
python -m pytest tests/test_dispatcher.py -v

# 用 -k 过滤某个测试类或方法
python -m pytest tests/test_personality_core.py -v -k TestApplyEmotionalShift
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
├── mocks.py                 # 共享 mock 工厂函数
│
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
├── test_memory_lifecycle.py # 记忆生命周期 Observation/FactV2 测试
├── test_embeddings.py       # 嵌入引擎与向量缓存测试
├── test_prompt_cache.py     # Prompt 分层缓存测试（#160）
│
├── test_context_manager.py  # 上下文管理测试
├── test_sleep_manager.py    # 睡眠管理测试
├── test_fact_checker.py     # FactChecker 测试
├── test_web_agent.py        # WebAgent 测试
├── test_session_manager.py  # Web 会话/角色绑定测试
├── test_file_tools.py       # 文件工具测试
├── test_music_tool.py       # 音乐工具测试
├── test_notify_tool.py      # 通知工具测试
├── test_prompt_instructions.py  # 指令模板测试
├── test_provider_abc.py     # LLMProvider ABC 测试（#23）
├── test_rate_limit.py       # 速率限制测试（#24）
├── test_conversation_examples.py  # 对话示例可配置测试（#28）
│
├── test_cognitive_state.py  # CognitiveState 测试
├── test_consolidation_unified.py  # 统一固化调用测试
├── test_proactivity.py      # 主动行为沉思循环测试
├── test_database_concurrency.py  # 数据库并发测试
├── test_inner_drive_state.py  # 内驱状态池测试
├── test_retrieval_pipeline.py  # 多阶段检索管线测试
│
├── test_v02_issues.py       # v0.2 issue 回归测试
│
├── real_api/                 # 需要真实 API 的集成测试（需 --real-api）
│   ├── conftest.py           # RealAPITestCase：无 flag 或无 key 时自动跳过
│   ├── test_provider.py
│   ├── test_inner_drive.py
│   ├── test_react_loop.py
│   └── test_dream.py
```

---

## Mock 策略

`tests/mocks.py` 提供了一组基于 `MagicMock` 的共享 mock 工厂函数：

### mock_provider

模拟 LLM API 返回，不发起真实 HTTP 请求：

```python
from tests.mocks import mock_provider

# 默认 generate 返回 "mock response"
provider = mock_provider()

# 自定义返回
provider = mock_provider(response="你好呀！")
```

### mock_personality & mock_ltm & mock_short_term

模拟人格情绪状态、长期记忆与短期记忆：

```python
from tests.mocks import mock_personality, mock_ltm, mock_short_term

personality = mock_personality(emotion_dominant="joy", arousal=0.7)
ltm = mock_ltm()   # facts/experiences 默认返回空，关系四维均为 0.5
stm = mock_short_term(turns=[{"role": "user", "content": "hi"}])
```

### mock_consolidator & mock_retriever & mock_tool_registry

模拟记忆合并器、检索器与工具注册表（`mock_tool_registry` 被 agent/工具相关测试广泛使用）：

```python
from tests.mocks import mock_consolidator, mock_retriever, mock_tool_registry

consolidator = mock_consolidator()  # analyze_sentiment 返回 (0.0, False, 0.5)
retriever = mock_retriever()        # retrieve_for_query 返回空 MemoryContext
registry = mock_tool_registry()     # 提供 10 个工具的 spec，execute 一律返回成功
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

现有测试多为 `unittest.TestCase` 风格（pytest 函数式同样支持）：

```python
import unittest
from tests.mocks import mock_provider, mock_ltm

class TestSomething(unittest.TestCase):
    def test_something(self):
        # Arrange
        provider = mock_provider(response="Hello!")
        ltm = mock_ltm()

        # Act
        result = some_function(provider, ltm)

        # Assert
        self.assertEqual(result, "expected")
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

### 真实 API 测试基类

`tests/real_api/` 下的测试继承 `RealAPITestCase`，未加 `--real-api` 标志或未配置 API key 时自动跳过：

```python
from tests.real_api.conftest import RealAPITestCase

class TestRealAPI(RealAPITestCase):
    def test_with_real_llm(self):
        # 只在 --real-api 标志且配置了 API key 时运行
        pass
```

### 新增功能测试要点

**Provider ABC（#23）**：验证自定义 Provider 必须实现 `generate` 方法，且 `DeepSeekProvider` 是 `LLMProvider` 子类。

```python
from core.provider import LLMProvider, DeepSeekProvider

assert issubclass(DeepSeekProvider, LLMProvider)
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

**记忆生命周期（Layer 1 一期）**：验证 `MemoryLifecycleManager` 的 observe/promote_fact/contradict_fact 等状态流转，repo 层用 `AsyncMock` 模拟（tests/test_memory_lifecycle.py）。

**Prompt 分层缓存（#160）**：验证 `PromptCache.get_or_build` 静态块不重复构建、慢变块 TTL 过期后重建（tests/test_prompt_cache.py）。

**嵌入引擎与向量缓存**：验证 `EmbeddingEngine` 空输入、缓存命中、API 失败降级及维度不匹配清缓存，生产维度为 1024（tests/test_embeddings.py）。

**SessionManager**：验证 Web 端会话与角色的绑定、复用与持久化（tests/test_session_manager.py）。

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
