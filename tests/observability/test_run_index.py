import json
import os

from observability.run_index import list_run_summaries


def _write_jsonl(path, events):
    lines = [json.dumps(event, ensure_ascii=False) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_lists_a_completed_run_with_parsed_metadata(tmp_path):
    path = tmp_path / "run-20260101-120000-aaaa.jsonl"
    _write_jsonl(path, [
        {"ts": "2026-01-01T12:00:00", "event": "session_start", "step": None,
         "payload": {"agent_name": "react_agent", "agent_type": "ReActAgent", "task_id": "task-1"}},
        {"ts": "2026-01-01T12:00:01", "event": "tool_call", "step": 1, "payload": {"tool_name": "echo"}},
        {"ts": "2026-01-01T12:00:02", "event": "model_output", "step": 1,
         "payload": {"usage": {"total_tokens": 10, "cost": 0.01}}},
        {"ts": "2026-01-01T12:00:05", "event": "session_end", "step": None, "payload": {"status": "completed"}},
    ])

    runs = list_run_summaries(tmp_path)

    assert len(runs) == 1
    run = runs[0]
    assert run["session_id"] == "run-20260101-120000-aaaa"
    assert run["agent_name"] == "react_agent"
    assert run["agent_type"] == "ReActAgent"
    assert run["task_id"] == "task-1"
    assert run["status"] == "completed"
    assert run["started_at"] == "2026-01-01T12:00:00"
    assert run["total_tokens"] == 10
    assert round(run["total_cost"], 3) == 0.01
    assert run["model_calls"] == 1
    assert run["duration_seconds"] == 5.0


def test_a_run_without_session_end_is_marked_running(tmp_path):
    path = tmp_path / "run-20260101-120000-bbbb.jsonl"
    _write_jsonl(path, [
        {"ts": "2026-01-01T12:00:00", "event": "session_start", "step": None,
         "payload": {"agent_name": "bot", "agent_type": "ReActAgent"}},
    ])

    runs = list_run_summaries(tmp_path)

    assert runs[0]["status"] == "running"
    assert runs[0]["duration_seconds"] == 0.0
    assert runs[0]["task_id"] is None


def test_skips_malformed_lines_but_keeps_the_rest(tmp_path):
    path = tmp_path / "run-20260101-120000-cccc.jsonl"
    good_line = json.dumps(
        {"ts": "2026-01-01T12:00:00", "event": "session_start", "step": None, "payload": {"agent_name": "bot"}}
    )
    path.write_text(good_line + "\n{not valid json\n", encoding="utf-8")

    runs = list_run_summaries(tmp_path)

    assert len(runs) == 1
    assert runs[0]["agent_name"] == "bot"


def test_a_file_with_no_session_start_is_skipped_entirely(tmp_path):
    path = tmp_path / "run-20260101-120000-dddd.jsonl"
    _write_jsonl(path, [
        {"ts": "2026-01-01T12:00:00", "event": "tool_call", "step": 1, "payload": {}},
    ])

    runs = list_run_summaries(tmp_path)

    assert runs == []


def test_returns_newest_first_and_respects_limit(tmp_path):
    for i in range(3):
        path = tmp_path / f"run-20260101-12000{i}-eeee.jsonl"
        _write_jsonl(path, [
            {"ts": "2026-01-01T12:00:00", "event": "session_start", "step": None,
             "payload": {"agent_name": f"bot-{i}"}},
        ])
        os.utime(path, (1000 + i, 1000 + i))

    runs = list_run_summaries(tmp_path, limit=2)

    assert [r["agent_name"] for r in runs] == ["bot-2", "bot-1"]


def test_missing_trace_dir_returns_empty_list(tmp_path):
    assert list_run_summaries(tmp_path / "does-not-exist") == []
