import json
import os

import pytest

from observability.run_recorder import RunRecorder, prune_sessions, redact


def test_init_creates_the_output_dir_and_opens_both_files(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path / "nested"))
    recorder.finalize()

    assert recorder.jsonl_path.exists()
    assert recorder.html_path.exists()
    assert recorder.jsonl_path.parent == tmp_path / "nested"


def test_log_event_appends_a_jsonl_line_per_event(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("session_start", {"agent_name": "bot"})
    recorder.log_event("tool_call", {"tool_name": "echo"}, step=1)
    recorder.finalize()

    lines = recorder.jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "session_start"
    assert first["session_id"] == recorder.session_id
    second = json.loads(lines[1])
    assert second["step"] == 1


def test_log_event_redacts_secrets_by_default(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("tool_call", {"auth": "Bearer sk-abc123"})
    recorder.finalize()

    line = recorder.jsonl_path.read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    assert record["payload"]["auth"] == "Bearer ***"


def test_log_event_skips_redaction_when_disabled(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path), redact_payloads=False)
    recorder.log_event("tool_call", {"auth": "Bearer sk-abc123"})
    recorder.finalize()

    record = json.loads(recorder.jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["payload"]["auth"] == "Bearer sk-abc123"


def test_events_returns_whats_logged_so_far_without_finalizing(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("session_start", {})
    recorder.log_event("tool_call", {"tool_name": "echo"}, step=1)

    events = recorder.events()

    assert [e["event"] for e in events] == ["session_start", "tool_call"]
    assert not recorder._jsonl_file.closed
    recorder.finalize()


def test_events_returns_a_copy(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("session_start", {})

    events = recorder.events()
    events.append({"event": "injected"})

    assert len(recorder.events()) == 1
    recorder.finalize()


def test_finalize_returns_the_summary_stats(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("tool_call", {"tool_name": "echo"}, step=1)

    stats = recorder.finalize()

    assert stats["tool_calls"] == {"echo": 1}
    assert stats["total_steps"] == 1


def test_html_report_escapes_injected_payload_content(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    recorder.log_event("tool_result", {"result": "<script>alert(1)</script>"})
    recorder.finalize()

    html = recorder.html_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_context_manager_finalizes_on_clean_exit(tmp_path):
    with RunRecorder(output_dir=str(tmp_path)) as recorder:
        recorder.log_event("session_start", {})

    assert recorder._jsonl_file.closed
    assert "Session Stats" in recorder.html_path.read_text(encoding="utf-8")


def test_footer_shows_cost_only_when_the_provider_reports_it(tmp_path):
    with_cost = RunRecorder(output_dir=str(tmp_path))
    with_cost.log_event("model_output", {"usage": {"total_tokens": 10, "cost": 0.0123}})
    with_cost.finalize()
    assert "Cost" in with_cost.html_path.read_text(encoding="utf-8")

    without_cost = RunRecorder(output_dir=str(tmp_path))
    without_cost.log_event("model_output", {"usage": {"total_tokens": 10}})
    without_cost.finalize()
    assert "Cost" not in without_cost.html_path.read_text(encoding="utf-8")


def test_prune_sessions_keeps_newest_and_deletes_both_files_per_session(tmp_path):
    for i in range(4):
        recorder = RunRecorder(output_dir=str(tmp_path), max_sessions=None)
        recorder.log_event("session_start", {"i": i})
        recorder.finalize()
        # 固定 mtime，避免同秒创建导致排序不稳定
        for path in (recorder.jsonl_path, recorder.html_path):
            os.utime(path, (1000 + i, 1000 + i))

    removed = prune_sessions(tmp_path, keep=2)

    assert removed == 4  # 删掉 2 个 session × 2 文件
    assert len(list(tmp_path.glob("run-*.jsonl"))) == 2
    assert len(list(tmp_path.glob("run-*.html"))) == 2


def test_run_recorder_prunes_old_sessions_when_max_sessions_is_set(tmp_path):
    for i in range(3):
        recorder = RunRecorder(output_dir=str(tmp_path), max_sessions=None)
        recorder.finalize()
        for path in (recorder.jsonl_path, recorder.html_path):
            os.utime(path, (2000 + i, 2000 + i))
    assert len(list(tmp_path.glob("run-*.jsonl"))) == 3

    newest = RunRecorder(output_dir=str(tmp_path), max_sessions=2)
    newest.finalize()

    # 保留 1 份旧 trace + 本次新建 = 2
    assert len(list(tmp_path.glob("run-*.jsonl"))) == 2


def test_context_manager_logs_the_exception_then_reraises(tmp_path):
    with pytest.raises(ValueError, match="boom"):
        with RunRecorder(output_dir=str(tmp_path)) as recorder:
            raise ValueError("boom")

    lines = recorder.jsonl_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["event"] == "error"
    assert record["payload"]["error_type"] == "ValueError"
    assert "boom" in record["payload"]["message"]
    assert "Traceback" in record["payload"]["traceback"]


def test_redact_masks_an_api_key():
    assert redact("key=sk-abc123XYZ") == "key=sk-***"


def test_redact_does_not_mangle_words_that_merely_contain_sk_dash():
    # \bsk- 的词边界：task-abc12345 / full-task-id-xyz 里的 "sk-" 不是密钥
    assert redact("task-abc12345") == "task-abc12345"
    assert redact("full-task-id-xyz") == "full-task-id-xyz"


def test_redact_masks_a_bearer_token():
    assert redact("Authorization: Bearer abcDEF-123_456") == "Authorization: Bearer ***"


def test_redact_masks_a_bearer_prefixed_api_key_without_double_masking():
    # "Bearer sk-..." matches both the bearer-token and api-key patterns; it must come out
    # masked once, not with asterisks stacked from both substitutions.
    assert redact("Authorization: Bearer sk-abc123XYZ") == "Authorization: Bearer ***"


def test_redact_masks_a_home_directory_username():
    assert redact("/Users/alice/project") == "/Users/***/project"
    assert redact("/home/bob/project") == "/home/***/project"


def test_redact_recurses_into_dicts_and_lists():
    value = {"headers": {"Authorization": "Bearer secret-token"}, "paths": ["/Users/alice/x"]}
    result = redact(value)
    assert result == {"headers": {"Authorization": "Bearer ***"}, "paths": ["/Users/***/x"]}


def test_redact_leaves_non_string_scalars_untouched():
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(3.14) == 3.14


def test_redact_leaves_text_without_secrets_unchanged():
    assert redact("just a normal sentence") == "just a normal sentence"
