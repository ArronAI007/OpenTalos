from datetime import datetime

import pytest
from pydantic import ValidationError

from core.protocol import ChatMessage, Completion, StreamSummary, ToolCompletion, ToolInvocation


def test_chat_message_defaults_timestamp_to_now():
    message = ChatMessage(content="hi", role="user")
    assert isinstance(message.timestamp, datetime)


def test_chat_message_to_dict_and_from_dict_round_trip():
    message = ChatMessage(content="hi", role="user", metadata={"k": "v"})
    data = message.to_dict()
    restored = ChatMessage.from_dict(data)
    assert restored.content == "hi"
    assert restored.role == "user"
    assert restored.metadata == {"k": "v"}


def test_chat_message_as_text_formats_role_and_content():
    message = ChatMessage(content="hello", role="assistant")
    assert message.as_text() == "[assistant] hello"


def test_chat_message_rejects_an_invalid_role():
    with pytest.raises(ValidationError):
        ChatMessage(content="hi", role="not-a-real-role")


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
