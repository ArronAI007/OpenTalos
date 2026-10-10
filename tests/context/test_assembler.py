from datetime import datetime, timedelta

from core.protocol import ChatMessage
from context.assembler import AssemblyConfig, ContextAssembler, ContextSlice


def test_assemble_includes_task_and_output_sections_by_default():
    assembler = ContextAssembler()
    result = assembler.assemble("what is the weather today")

    assert "[Task]\nwhat is the weather today" in result
    assert "[Output]" in result


def test_assemble_includes_pinned_system_instructions():
    assembler = ContextAssembler()
    result = assembler.assemble("hello", system_instructions="Always be concise.")

    assert "[Role & Policies]" in result
    assert "Always be concise." in result


def test_assemble_includes_recent_transcript_as_context():
    assembler = ContextAssembler()
    transcript = [
        ChatMessage(content="hi", role="user"),
        ChatMessage(content="hello there", role="assistant"),
    ]

    result = assembler.assemble("hi", transcript=transcript)

    assert "[Context]" in result
    assert "[user] hi" in result


def test_low_relevance_slices_are_dropped():
    config = AssemblyConfig(min_relevance=0.5, enable_mmr=False)
    assembler = ContextAssembler(config)
    slices = [ContextSlice(content="totally unrelated filler text", kind="evidence")]

    result = assembler.assemble("weather forecast", extra_slices=slices)

    assert "totally unrelated filler text" not in result


def test_relevant_evidence_slice_is_included():
    config = AssemblyConfig(min_relevance=0.1, enable_mmr=False)
    assembler = ContextAssembler(config)
    slices = [ContextSlice(content="the weather forecast says rain", kind="evidence")]

    result = assembler.assemble("weather forecast", extra_slices=slices)

    assert "[Evidence]" in result
    assert "the weather forecast says rain" in result


def test_memory_and_knowledge_slices_are_grouped_under_evidence():
    config = AssemblyConfig(min_relevance=0.1, enable_mmr=False)
    assembler = ContextAssembler(config)
    slices = [
        ContextSlice(content="weather note: bring an umbrella", kind="memory"),
        ContextSlice(content="weather fact: rain is water falling from clouds", kind="knowledge"),
    ]

    result = assembler.assemble("weather", extra_slices=slices)

    assert "[Evidence]" in result
    assert "bring an umbrella" in result
    assert "rain is water falling from clouds" in result


def test_state_slice_gets_its_own_section():
    config = AssemblyConfig(min_relevance=0.1, enable_mmr=False)
    assembler = ContextAssembler(config)
    slices = [ContextSlice(content="task progress: step 2 of 3 complete, waiting on approval", kind="state")]

    result = assembler.assemble("task progress", extra_slices=slices)

    assert "[State]" in result
    assert "step 2 of 3 complete, waiting on approval" in result
    assert result.index("[State]") < result.index("[Output]")


def test_mmr_prefers_diverse_slices_over_near_duplicates():
    config = AssemblyConfig(min_relevance=0.0, enable_mmr=True, mmr_lambda=0.5, max_tokens=60, reserve_ratio=0.0)
    assembler = ContextAssembler(config)
    slices = [
        ContextSlice(content="weather forecast rain today", kind="evidence"),
        ContextSlice(content="weather forecast rain today again", kind="evidence"),
        ContextSlice(content="stock market closed for holiday", kind="evidence"),
    ]

    result = assembler.assemble("weather forecast rain", extra_slices=slices)

    assert "stock market closed for holiday" in result


def test_condense_truncates_when_over_budget():
    config = AssemblyConfig(max_tokens=20, reserve_ratio=0.0, min_relevance=0.0)
    assembler = ContextAssembler(config)
    slices = [ContextSlice(content=f"filler line number {i} about testing" * 3, kind="evidence") for i in range(10)]

    result = assembler.assemble("testing", extra_slices=slices)

    assert assembler._tokens.estimate_text(result) <= config.budget_tokens


def test_condense_is_skipped_when_compression_disabled():
    config = AssemblyConfig(max_tokens=5, reserve_ratio=0.0, enable_compression=False)
    assembler = ContextAssembler(config)

    result = assembler.assemble("a longer query than the tiny budget allows")

    assert "[Output]" in result


def test_recency_favors_newer_slices_when_relevance_ties():
    config = AssemblyConfig(min_relevance=0.0, enable_mmr=False, max_tokens=1000)
    assembler = ContextAssembler(config)
    old_slice = ContextSlice(
        content="irrelevant but old",
        kind="evidence",
        timestamp=datetime.now() - timedelta(hours=10),
    )
    new_slice = ContextSlice(content="irrelevant but new", kind="evidence")

    result = assembler.assemble("irrelevant", extra_slices=[old_slice, new_slice])

    assert result.index("irrelevant but new") < result.index("irrelevant but old")


def _turn(user_content: str, assistant_content: str) -> list[ChatMessage]:
    return [
        ChatMessage(content=user_content, role="user"),
        ChatMessage(content=assistant_content, role="assistant"),
    ]


def test_select_recent_turns_keeps_most_recent_turns_within_budget():
    assembler = ContextAssembler()
    turns = [_turn(f"question {i}", f"answer {i}") for i in range(5)]
    messages = [m for turn in turns for m in turn]
    one_turn_tokens = assembler._tokens.estimate_messages(turns[-1])
    budget = one_turn_tokens * 2 + 1  # 刚好够装下最近两轮

    selected = assembler.select_recent_turns(messages, budget)

    assert selected == turns[-2] + turns[-1]


def test_select_recent_turns_never_splits_a_tool_call_pair():
    # 预算小到理论上只能塞下 tool 那一条消息，但筛选是整轮粒度，不能把 tool_calls 和它的
    # 结果拆开——所以要么整轮三条都在，要么一条都不在（这里断言整轮都在，因为"至少保留
    # 最新一轮"的保证）。
    messages = [
        ChatMessage(content="查一下", role="user"),
        ChatMessage(
            content="echoed: hi", role="tool",
            metadata={"tool_call_id": "c1", "tool_name": "echo", "arguments": '{"text": "hi"}'},
        ),
        ChatMessage(content="结果是 hi", role="assistant"),
    ]
    assembler = ContextAssembler()

    selected = assembler.select_recent_turns(messages, budget_tokens=1)

    assert selected == messages


def test_select_recent_turns_keeps_at_least_the_newest_turn_even_if_it_exceeds_budget():
    assembler = ContextAssembler()
    turns = [_turn(f"question {i}", f"answer {i}") for i in range(3)]
    messages = [m for turn in turns for m in turn]

    selected = assembler.select_recent_turns(messages, budget_tokens=1)

    assert selected == turns[-1]


def test_select_recent_turns_returns_empty_for_empty_input():
    assembler = ContextAssembler()
    assert assembler.select_recent_turns([], budget_tokens=1000) == []


def test_select_recent_turns_preserves_chronological_order():
    assembler = ContextAssembler()
    turns = [_turn(f"question {i}", f"answer {i}") for i in range(4)]
    messages = [m for turn in turns for m in turn]
    budget = assembler._tokens.estimate_messages(messages) * 10  # 预算远超全部历史

    selected = assembler.select_recent_turns(messages, budget)

    assert selected == messages


def test_select_recent_turns_treats_a_leading_non_user_message_as_its_own_turn():
    messages = [
        ChatMessage(content="earlier discussion", role="summary"),
        ChatMessage(content="new question", role="user"),
        ChatMessage(content="new answer", role="assistant"),
    ]
    assembler = ContextAssembler()
    budget = assembler._tokens.estimate_messages(messages)  # 刚好够装下全部

    selected = assembler.select_recent_turns(messages, budget)

    assert selected == messages


def test_select_relevant_turns_equals_recent_when_within_budget():
    assembler = ContextAssembler()
    turns = [_turn(f"question {i}", f"answer {i}") for i in range(3)]
    messages = [m for turn in turns for m in turn]
    budget = assembler._tokens.estimate_messages(messages) * 2  # 远超全部

    assert assembler.select_relevant_turns(messages, "anything", budget) == messages


def test_select_relevant_turns_retrieves_a_relevant_older_turn():
    assembler = ContextAssembler()
    turns = [_turn("python 数据分析怎么做", "用 pandas")]
    turns += [_turn(f"无关闲聊 {i}", f"嗯 {i}") for i in range(1, 8)]
    messages = [m for turn in turns for m in turn]
    budget = assembler._tokens.estimate_messages(turns[-1]) * 3  # 大概够 3 轮

    selected = assembler.select_relevant_turns(messages, "python 数据分析", budget, max_recent_turns=2)

    contents = [m.content for m in selected]
    assert contents[0] == "python 数据分析怎么做"  # 相关旧轮被召回且在最前（保持时间序）
    assert "无关闲聊 1" not in contents  # 无关的较早轮次被丢弃


def test_select_relevant_turns_keeps_only_recent_when_nothing_older_matches():
    assembler = ContextAssembler()
    turns = [_turn(f"无关闲聊 {i}", f"嗯 {i}") for i in range(8)]
    messages = [m for turn in turns for m in turn]
    budget = assembler._tokens.estimate_messages(turns[-1]) * 3

    selected = assembler.select_relevant_turns(messages, "python 数据分析", budget, max_recent_turns=2)

    assert selected == turns[-2] + turns[-1]
