from core.protocol import ChatMessage
from context.transcript import TranscriptStore


def _turn(store: TranscriptStore, user_text: str, assistant_text: str) -> None:
    store.append(ChatMessage(content=user_text, role="user"))
    store.append(ChatMessage(content=assistant_text, role="assistant"))


def test_append_and_messages_returns_a_copy():
    store = TranscriptStore()
    store.append(ChatMessage(content="hi", role="user"))

    messages = store.messages()
    messages.append(ChatMessage(content="injected", role="user"))

    assert len(store.messages()) == 1


def test_clear_empties_the_transcript():
    store = TranscriptStore()
    store.append(ChatMessage(content="hi", role="user"))
    store.clear()
    assert store.messages() == []


def test_turn_count_counts_one_turn_per_user_message():
    store = TranscriptStore()
    _turn(store, "hi", "hello")
    _turn(store, "how are you", "good")
    assert store.turn_count() == 2


def test_compress_is_a_noop_below_the_retain_threshold():
    store = TranscriptStore(min_retain_turns=5)
    _turn(store, "hi", "hello")

    changed = store.compress("summary")
    assert changed is False
    assert store.turn_count() == 1


def test_compress_folds_older_turns_into_a_summary_message():
    store = TranscriptStore(min_retain_turns=2)
    for i in range(4):
        _turn(store, f"question {i}", f"answer {i}")

    changed = store.compress("earlier discussion")
    assert changed is True

    messages = store.messages()
    assert messages[0].role == "summary"
    assert "earlier discussion" in messages[0].content
    # summary + the last 2 retained turns (4 messages)
    assert len(messages) == 5
    assert store.turn_count() == 2


def test_snapshot_and_restore_round_trip():
    store = TranscriptStore()
    _turn(store, "hi", "hello")

    data = store.snapshot()
    assert data["turns"] == 1

    restored = TranscriptStore()
    restored.restore(data)
    assert [m.content for m in restored.messages()] == ["hi", "hello"]
