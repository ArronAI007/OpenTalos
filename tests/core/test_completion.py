from core.completion import Completion, StreamSummary, ToolCompletion, ToolInvocation


def test_completion_str_returns_text():
    completion = Completion(text="hello", model_id="mock-model")
    assert str(completion) == "hello"


def test_completion_to_dict_includes_all_fields():
    completion = Completion(text="hi", model_id="mock-model")
    assert completion.to_dict() == {
        "text": "hi",
        "model_id": "mock-model",
        "token_usage": {},
        "duration_ms": 0,
        "thinking_trace": None,
    }


def test_completion_to_dict_includes_thinking_trace_when_present():
    completion = Completion(text="hi", model_id="mock-model", thinking_trace="because")
    assert completion.to_dict()["thinking_trace"] == "because"


def test_tool_invocation_and_tool_completion_hold_expected_fields():
    invocation = ToolInvocation(call_id="1", tool_name="search", arguments_json='{"q": "x"}')
    completion = ToolCompletion(text=None, requested_tools=[invocation], model_id="mock-model")
    assert completion.requested_tools == [invocation]
    assert completion.text is None


def test_stream_summary_to_dict_includes_thinking_trace_when_present():
    summary = StreamSummary(model_id="mock-model", thinking_trace="thinking")
    assert summary.to_dict()["thinking_trace"] == "thinking"
