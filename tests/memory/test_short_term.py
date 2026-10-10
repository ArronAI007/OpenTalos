from core.protocol import ChatMessage
from memory.short_term import seed_messages


def test_seed_messages_includes_system_history_and_query():
    history = [ChatMessage(content="hi", role="user"), ChatMessage(content="hello", role="assistant")]
    messages = seed_messages("Be nice.", history, "what's next?")

    assert messages[0] == {"role": "system", "content": "Be nice."}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert messages[2] == {"role": "assistant", "content": "hello"}
    assert messages[3] == {"role": "user", "content": "what's next?"}


def test_seed_messages_omits_system_block_when_no_prompt():
    messages = seed_messages(None, [], "hi")
    assert messages == [{"role": "user", "content": "hi"}]


def test_seed_messages_rehydrates_tool_history():
    history = [
        ChatMessage(content="查一下", role="user"),
        ChatMessage(
            content="echoed: hi",
            role="tool",
            metadata={"tool_call_id": "c1", "tool_name": "echo", "arguments": '{"text": "hi"}'},
        ),
        ChatMessage(content="结果是 hi", role="assistant"),
    ]

    messages = seed_messages(None, history, "再来一次")

    assert messages == [
        {"role": "user", "content": "查一下"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "hi"}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "echoed: hi"},
        {"role": "assistant", "content": "结果是 hi"},
        {"role": "user", "content": "再来一次"},
    ]


def test_seed_messages_maps_summary_to_system_block():
    history = [
        ChatMessage(content="earlier", role="summary"),
        ChatMessage(content="recent user", role="user"),
        ChatMessage(content="recent assistant", role="assistant"),
    ]
    messages = seed_messages("Be nice.", history, "now?")

    assert messages == [
        {"role": "system", "content": "Be nice."},
        {"role": "system", "content": "## Archived Session Summary\nearlier"},
        {"role": "user", "content": "recent user"},
        {"role": "assistant", "content": "recent assistant"},
        {"role": "user", "content": "now?"},
    ]
