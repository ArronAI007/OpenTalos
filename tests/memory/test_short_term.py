from core.protocol import ChatMessage
from context import AssemblyConfig
from memory.short_term import ShortTermMemory, seed_messages


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


def test_short_term_memory_append_and_messages_round_trip():
    memory = ShortTermMemory()
    memory.append(ChatMessage(content="hi", role="user"))
    memory.append(ChatMessage(content="hello", role="assistant"))

    assert [m.content for m in memory.messages()] == ["hi", "hello"]


def test_short_term_memory_clear():
    memory = ShortTermMemory()
    memory.append(ChatMessage(content="hi", role="user"))
    memory.clear()
    assert memory.messages() == []


def test_short_term_memory_compress_folds_old_turns():
    memory = ShortTermMemory(min_retain_turns=1)
    for i in range(4):
        memory.append(ChatMessage(content=f"question {i}", role="user"))
        memory.append(ChatMessage(content=f"answer {i}", role="assistant"))

    changed = memory.compress("earlier discussion")

    assert changed is True
    assert memory.messages()[0].role == "summary"
    assert "earlier discussion" in memory.messages()[0].content


def test_short_term_memory_snapshot_and_restore_round_trip():
    memory = ShortTermMemory()
    memory.append(ChatMessage(content="hi", role="user"))
    data = memory.snapshot()

    restored = ShortTermMemory()
    restored.restore(data)

    assert [m.content for m in restored.messages()] == ["hi"]


def test_short_term_memory_exposes_its_assembler():
    memory = ShortTermMemory()
    assert hasattr(memory.assembler, "assemble")
    assert hasattr(memory.assembler, "select_recent_turns")


def test_build_messages_uses_system_prompt_and_own_history():
    memory = ShortTermMemory()
    memory.append(ChatMessage(content="hi", role="user"))
    memory.append(ChatMessage(content="hello", role="assistant"))

    messages = memory.build_messages("Be nice.", "what's next?")

    assert messages[0] == {"role": "system", "content": "Be nice."}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert messages[2] == {"role": "assistant", "content": "hello"}
    assert messages[3] == {"role": "user", "content": "what's next?"}


def test_build_messages_truncates_history_via_token_budget():
    config = AssemblyConfig(max_tokens=10, reserve_ratio=0.0)
    memory = ShortTermMemory(context_config=config)
    for i in range(10):
        memory.append(ChatMessage(content=f"question {i}" * 20, role="user"))
        memory.append(ChatMessage(content=f"answer {i}" * 20, role="assistant"))

    messages = memory.build_messages(None, "latest question")

    # 预算很小：不应该把全部 20 条历史都塞进去，但至少保留了最新一轮（倒数第二、第三条）
    assert len(messages) < 21
    assert messages[-2] == {"role": "assistant", "content": "answer 9" * 20}
