import asyncio
import json
from pathlib import Path

import pytest

from privacy.engine import PrivacyBlockedError, PrivacyEngine, PrivacyUnavailableError
from privacy.store import PrivacyRule, PrivacyStore


def test_builtin_rules_mask_stably_without_auditing_secret_values(tmp_path: Path) -> None:
    store = PrivacyStore(tmp_path / "privacy.db")
    engine = PrivacyEngine(store)
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"

    first = engine.mask_text(
        f"email me at alice@example.com with {secret}",
        scope="thread-1",
        request_id="req-1",
    )
    second = engine.mask_text(
        f"again alice@example.com and {secret}",
        scope="thread-1",
        request_id="req-2",
    )

    assert "alice@example.com" not in first.text
    assert secret not in first.text
    assert first.placeholders["email"] == second.placeholders["email"]
    assert first.placeholders["openai_key"] == second.placeholders["openai_key"]
    assert secret not in json.dumps(store.list_audit(), ensure_ascii=False)
    assert engine.restore_text(first.text, scope="thread-1") == (
        f"email me at alice@example.com with {secret}"
    )


def test_rules_support_mask_warn_and_block_actions(tmp_path: Path) -> None:
    store = PrivacyStore(tmp_path / "privacy.db")
    store.save_rule(
        PrivacyRule(
            id="project_codename",
            title="Project codename",
            pattern=r"Bluebird",
            action="warn",
        )
    )
    store.save_rule(
        PrivacyRule(
            id="forbidden_marker",
            title="Forbidden marker",
            pattern=r"DO_NOT_SEND",
            action="block",
        )
    )
    engine = PrivacyEngine(store)

    warned = engine.mask_text("Bluebird is ready", scope="warn", request_id="warn")
    assert warned.text == "Bluebird is ready"
    assert warned.warnings
    assert store.list_audit()[0]["action"] == "warn"

    with pytest.raises(PrivacyBlockedError) as error:
        engine.mask_text(
            "DO_NOT_SEND this",
            scope="block",
            request_id="block",
        )
    assert error.value.status_code == 451
    assert "forbidden_marker" in str(error.value)


def test_mask_and_restore_nested_request_response_reasoning_and_tools(
    tmp_path: Path,
) -> None:
    engine = PrivacyEngine(PrivacyStore(tmp_path / "privacy.db"))
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": "email alice@example.com",
                "reasoning_content": "ask bob@example.com",
                "tool_calls": [
                    {
                        "function": {
                            "name": "send",
                            "arguments": '{"to":"alice@example.com"}',
                        }
                    }
                ],
            }
        ]
    }

    masked = engine.mask_payload(payload, scope="thread")
    serialized = json.dumps(masked.payload)

    assert "alice@example.com" not in serialized
    assert "bob@example.com" not in serialized
    restored = engine.restore_payload(masked.payload, scope="thread")
    assert restored["messages"][0]["content"] == "email alice@example.com"
    assert restored["messages"][0]["reasoning_content"] == "ask bob@example.com"
    assert "alice@example.com" in restored["messages"][0]["tool_calls"][0]["function"][
        "arguments"
    ]


def test_stream_restore_covers_text_reasoning_and_tool_arguments(tmp_path: Path) -> None:
    engine = PrivacyEngine(PrivacyStore(tmp_path / "privacy.db"))
    masked = engine.mask_payload(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "alice@example.com bob@example.com carol@example.com",
                }
            ]
        },
        scope="stream",
    )
    source_text = masked.payload["messages"][0]["content"]
    tokens = list(masked.token_to_value)
    content_token, reasoning_token, tool_token = tokens[:3]
    event = {
        "choices": [
            {
                "delta": {
                    "content": f"email {content_token}",
                    "reasoning_content": f"call {reasoning_token}",
                    "tool_calls": [
                        {
                            "function": {
                                "arguments": json.dumps({"to": tool_token})
                            }
                        }
                    ],
                }
            }
        ]
    }

    async def source():
        yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    async def collect() -> str:
        return "".join(
            [chunk async for chunk in engine.restore_sse(source(), scope="stream")]
        )

    rendered = asyncio.run(collect())

    assert "alice@example.com" in rendered
    assert "bob@example.com" in rendered
    assert "carol@example.com" in rendered
    assert source_text not in rendered


def test_fail_closed_blocks_when_rule_evaluation_fails(tmp_path: Path) -> None:
    def broken_rules():
        raise RuntimeError("rule store unavailable")

    engine = PrivacyEngine(
        PrivacyStore(tmp_path / "privacy.db"),
        rule_loader=broken_rules,
        fail_closed=True,
    )

    with pytest.raises(PrivacyUnavailableError, match="rule store unavailable"):
        engine.mask_text("hello", scope="thread")
