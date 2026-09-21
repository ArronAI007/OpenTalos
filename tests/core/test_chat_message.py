from datetime import datetime

import pytest
from pydantic import ValidationError

from core.chat_message import ChatMessage


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
