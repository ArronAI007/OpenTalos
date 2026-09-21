from datetime import datetime

from context.message import Note


def test_note_defaults_timestamp_to_now():
    note = Note(content="hi", role="user")
    assert isinstance(note.timestamp, datetime)


def test_note_to_dict_and_from_dict_round_trip():
    note = Note(content="hi", role="user", metadata={"k": "v"})
    restored = Note.from_dict(note.to_dict())
    assert restored.content == "hi"
    assert restored.role == "user"
    assert restored.metadata == {"k": "v"}


def test_note_as_text_formats_role_and_content():
    note = Note(content="hello", role="assistant")
    assert note.as_text() == "[assistant] hello"


def test_note_from_dict_defaults_missing_metadata_to_none():
    restored = Note.from_dict({"content": "hi", "role": "user", "timestamp": datetime.now().isoformat()})
    assert restored.metadata is None
