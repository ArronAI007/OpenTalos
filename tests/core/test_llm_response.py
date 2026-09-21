from core.llm_response import LLMResponse, LLMToolResponse, StreamStats, ToolCall


def test_llm_response_str_returns_content():
    response = LLMResponse(content="hello", model="mock-model")
    assert str(response) == "hello"


def test_llm_response_to_dict_includes_all_fields():
    response = LLMResponse(content="hi", model="mock-model")
    assert response.to_dict() == {
        "content": "hi",
        "model": "mock-model",
        "usage": {},
        "latency_ms": 0,
        "reasoning_content": None,
    }


def test_llm_response_to_dict_includes_reasoning_content_when_present():
    response = LLMResponse(content="hi", model="mock-model", reasoning_content="because")
    assert response.to_dict()["reasoning_content"] == "because"


def test_tool_call_and_llm_tool_response_hold_expected_fields():
    tool_call = ToolCall(id="1", name="search", arguments='{"q": "x"}')
    response = LLMToolResponse(content=None, tool_calls=[tool_call], model="mock-model")
    assert response.tool_calls == [tool_call]
    assert response.content is None


def test_stream_stats_to_dict_includes_reasoning_content_when_present():
    stats = StreamStats(model="mock-model", reasoning_content="thinking")
    assert stats.to_dict()["reasoning_content"] == "thinking"
