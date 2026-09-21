from datetime import datetime, timedelta

from core.chat_message import ChatMessage
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
