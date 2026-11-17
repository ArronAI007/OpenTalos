import json
from pathlib import Path

import pytest

from agent_platform.sessions import LocalSessionNotFoundError, LocalSessionService


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def local_home(tmp_path: Path) -> Path:
    codex_id = "11111111-1111-1111-1111-111111111111"
    _write_jsonl(
        tmp_path / ".codex" / "session_index.jsonl",
        [
            {
                "id": codex_id,
                "thread_name": "Codex local session",
                "updated_at": "2026-11-17T01:00:00Z",
            }
        ],
    )
    _write_jsonl(
        tmp_path
        / ".codex"
        / "sessions"
        / "2026"
        / "11"
        / "17"
        / f"rollout-2026-11-17T09-00-00-{codex_id}.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": codex_id,
                    "cwd": "/work/opentalos",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>ignored</environment_context>",
                        },
                        {"type": "input_text", "text": "继续实现会话列表"},
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "开始实现。"}],
                },
            },
        ],
    )

    claude_id = "22222222-2222-2222-2222-222222222222"
    _write_jsonl(
        tmp_path
        / ".claude"
        / "projects"
        / "-work-claude"
        / f"{claude_id}.jsonl",
        [
            {
                "type": "user",
                "sessionId": claude_id,
                "cwd": "/work/claude",
                "timestamp": "2026-11-16T10:00:00Z",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "检查 Claude 会话"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-11-16T10:01:00Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet",
                    "content": [{"type": "text", "text": "已经检查。"}],
                },
            },
            {
                "type": "cost-state",
                "totalCostUSD": 0.12,
                "modelUsage": {
                    "claude-sonnet": {
                        "inputTokens": 120,
                        "outputTokens": 30,
                        "cacheReadInputTokens": 50,
                    }
                },
            },
        ],
    )

    pi_id = "33333333-3333-3333-3333-333333333333"
    _write_jsonl(
        tmp_path
        / ".pi"
        / "agent"
        / "sessions"
        / "--work-pi--"
        / f"2026-11-15T09-00-00-000Z_{pi_id}.jsonl",
        [
            {
                "type": "session",
                "id": pi_id,
                "cwd": "/work/pi",
                "timestamp": "2026-11-15T09:00:00Z",
            },
            {"type": "model_change", "provider": "openai", "modelId": "gpt-5"},
            {
                "type": "message",
                "timestamp": "2026-11-15T09:01:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "检查 Pi 会话"}],
                },
            },
            {
                "type": "message",
                "timestamp": "2026-11-15T09:02:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Pi 正常。"}],
                    "usage": {
                        "input": 80,
                        "output": 20,
                        "totalTokens": 100,
                        "cost": {"input": 0.01, "output": 0.02},
                    },
                },
            },
        ],
    )
    return tmp_path


def test_lists_and_reads_codex_claude_and_pi_sessions(local_home: Path) -> None:
    service = LocalSessionService(local_home)

    listing = service.list_sessions()

    assert {item["id"]: item["count"] for item in listing["sources"]} == {
        "codex": 1,
        "claude-code": 1,
        "pi": 1,
    }
    sessions = {item["source"]: item for item in listing["sessions"]}
    assert sessions["codex"]["title"] == "Codex local session"
    assert sessions["codex"]["cwd"] == "/work/opentalos"
    assert sessions["claude-code"]["title"] == "检查 Claude 会话"
    assert sessions["claude-code"]["cost_usd"] == 0.12
    assert sessions["pi"]["model"] == "gpt-5"
    assert sessions["pi"]["total_tokens"] == 100

    codex = service.get_session(
        "codex",
        "11111111-1111-1111-1111-111111111111",
    )
    assert [message["role"] for message in codex["messages"]] == [
        "user",
        "assistant",
    ]
    assert codex["messages"][0]["content"] == "继续实现会话列表"
    assert codex["messages"][1]["content"] == "开始实现。"


def test_filters_sessions_and_rejects_unknown_ids(local_home: Path) -> None:
    service = LocalSessionService(local_home)

    filtered = service.list_sessions(source="pi", query="work/pi")

    assert [item["source"] for item in filtered["sessions"]] == ["pi"]
    with pytest.raises(LocalSessionNotFoundError):
        service.get_session("codex", "../../etc/passwd")
    with pytest.raises(LocalSessionNotFoundError):
        service.get_session(
            "codex",
            "99999999-9999-9999-9999-999999999999",
        )
