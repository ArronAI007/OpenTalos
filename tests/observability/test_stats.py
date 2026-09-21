from observability.stats import summarize


def test_summarize_counts_steps_tokens_and_model_calls():
    events = [
        {"ts": "2026-01-01T00:00:00", "event": "session_start", "step": None, "payload": {}},
        {"ts": "2026-01-01T00:00:01", "event": "model_output", "step": 1, "payload": {"usage": {"total_tokens": 10, "cost": 0.01}}},
        {"ts": "2026-01-01T00:00:02", "event": "model_output", "step": 2, "payload": {"usage": {"total_tokens": 5, "cost": 0.005}}},
        {"ts": "2026-01-01T00:00:03", "event": "session_end", "step": None, "payload": {}},
    ]

    stats = summarize(events)

    assert stats["total_steps"] == 2
    assert stats["total_tokens"] == 15
    assert round(stats["total_cost"], 3) == 0.015
    assert stats["model_calls"] == 2
    assert stats["duration_seconds"] == 3.0


def test_summarize_counts_tool_calls_per_tool_name():
    events = [
        {"ts": "t", "event": "tool_call", "step": 1, "payload": {"tool_name": "echo"}},
        {"ts": "t", "event": "tool_call", "step": 2, "payload": {"tool_name": "echo"}},
        {"ts": "t", "event": "tool_call", "step": 3, "payload": {"tool_name": "search"}},
    ]

    stats = summarize(events)

    assert stats["tool_calls"] == {"echo": 2, "search": 1}


def test_summarize_collects_errors():
    events = [
        {"ts": "t", "event": "error", "step": 3, "payload": {"error_type": "ValueError", "message": "boom"}},
    ]

    stats = summarize(events)

    assert stats["errors"] == [{"step": 3, "type": "ValueError", "message": "boom"}]


def test_summarize_of_an_empty_run_has_zeroed_out_stats():
    stats = summarize([])
    assert stats["total_steps"] == 0
    assert stats["total_tokens"] == 0
    assert stats["duration_seconds"] == 0.0
    assert stats["tool_calls"] == {}
    assert stats["errors"] == []
