"""Shared mock factories for unit tests."""
from unittest.mock import MagicMock


def mock_provider(response="mock response"):
    m = MagicMock()
    m.generate.return_value = response
    return m


def mock_personality(emotion_dominant="neutral", arousal=0.5, valence=0.4):
    m = MagicMock()
    m.emotion.dominant_emotion = emotion_dominant
    m.emotion.arousal = arousal
    m.emotion.valence = valence
    m.emotion.resentment = 0.0
    m.emotion.record_emotion_event = MagicMock()
    m.emotion.emotion_events = []
    m.config.interests = ["music", "art", "technology"]
    return m


def mock_ltm():
    m = MagicMock()
    m.get_all_active_facts.return_value = []
    m.get_recent_experiences.return_value = []
    m.get_relationship.return_value = {
        "trust": 0.5, "familiarity": 0.5,
        "intimacy": 0.5, "playfulness": 0.5,
    }
    return m


def mock_short_term(turns=None):
    m = MagicMock()
    m.get_recent.return_value = turns or []
    m.get_all.return_value = turns or []
    m.get_all_reversed.return_value = list(reversed(turns or []))
    return m


def mock_consolidator():
    m = MagicMock()
    m.analyze_sentiment.return_value = (0.0, False, 0.5)
    return m


def mock_retriever():
    m = MagicMock()
    from models.conversation import MemoryContext
    m.retrieve_for_query.return_value = MemoryContext(
        facts=[], experiences=[], reflections=[],
        relationship={"trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5},
    )
    return m


def mock_tool_registry():
    """Mock ToolRegistry with proper specs for format_for_prompt() and get()."""
    m = MagicMock()
    from tools.traits import ToolSpec, ToolResult

    specs = []
    for name in ["web_fetch", "web_search", "read_file", "file_tree", "glob", "grep",
                  "music_play", "notify", "recall", "remember"]:
        specs.append(ToolSpec(
            name=name,
            description=f"Mock {name} tool",
            parameters={"type": "object", "properties": {}},
        ))
    m.list_specs.return_value = specs

    def _make_mock_tool(tool_name):
        t = MagicMock()
        t.execute.return_value = ToolResult(success=True, output="mock tool output")
        t.spec.return_value = ToolSpec(name=tool_name, description="mock", parameters={})
        t.name.return_value = tool_name
        return t

    m.get.side_effect = lambda name: _make_mock_tool(name)
    return m
