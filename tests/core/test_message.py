from datetime import datetime

import pytest
from pydantic import ValidationError

from core.message import Message


def test_message_defaults_timestamp_to_now():
    message = Message(content="hi", role="user")
    assert isinstance(message.timestamp, datetime)


def test_message_to_dict_and_from_dict_round_trip():
    message = Message(content="hi", role="user", metadata={"k": "v"})
    data = message.to_dict()
    restored = Message.from_dict(data)
    assert restored.content == "hi"
    assert restored.role == "user"
    assert restored.metadata == {"k": "v"}


def test_message_to_text_formats_role_and_content():
    message = Message(content="hello", role="assistant")
    assert message.to_text() == "[assistant] hello"


def test_message_rejects_an_invalid_role():
    with pytest.raises(ValidationError):
        Message(content="hi", role="not-a-real-role")
