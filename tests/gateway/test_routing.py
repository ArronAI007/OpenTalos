import datetime
from pathlib import Path

import pytest

from gateway.request_log import GatewayRequestLog
from gateway.routing import RoutingEngine, RoutingError
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor


def _fixed_now() -> datetime.datetime:
    return datetime.datetime(2026, 11, 16, 12, 0, 0)


def _store(tmp_path: Path) -> tuple[ControlPlaneStore, dict, dict, dict]:
    store = ControlPlaneStore(tmp_path / "routing.db")
    accounts = {}
    for provider, name, model in (
        ("openai", "Primary", "gpt-4o"),
        ("openai", "Backup", "gpt-4o"),
        ("anthropic", "Claude", "claude-sonnet-5"),
    ):
        account = store.create_account(
            provider=provider,
            name=name,
            backend="anthropic" if provider == "anthropic" else "openai-compatible",
            base_url=None if provider == "anthropic" else "https://example.test/v1",
            api_key=f"{name}-key",
        )
        store.replace_models(
            account["id"],
            [
                ModelDescriptor(
                    model,
                    model,
                    "anthropic-messages" if provider == "anthropic" else "openai-chat",
                    None,
                    True,
                    False,
                    "provider",
                )
            ],
        )
        accounts[name] = account
    return store, accounts["Primary"], accounts["Backup"], accounts["Claude"]


def test_routing_group_order_nested_and_session_sticky(tmp_path: Path) -> None:
    store, primary, backup, claude = _store(tmp_path)
    store.create_routing_group(
        name="coding",
        mode="order",
        sticky=True,
        members=[
            {"target": f"openai/Backup/gpt-4o"},
            {"target": "group/claude"},
        ],
    )
    store.create_routing_group(
        name="claude",
        mode="order",
        members=[{"target": "anthropic/claude-sonnet-5"}],
    )
    router = RoutingEngine(store, now=_fixed_now)

    decision = router.decide("group/coding", session_key="thread-1")

    assert [candidate.account_name for candidate in decision.candidates] == [
        "Backup",
        "Claude",
    ]
    assert decision.group_name == "coding"
    assert decision.trace["mode"] == "order"

    store.update_routing_group(
        "coding",
        members=[
            {"target": "anthropic/claude-sonnet-5"},
            {"target": "openai/Primary/gpt-4o"},
            {"target": "openai/Backup/gpt-4o"},
        ],
    )
    sticky = router.decide("group/coding", session_key="thread-1")
    assert sticky.candidates[0].account_name == "Backup"


def test_routing_rotate_advances_cursor(tmp_path: Path) -> None:
    store, *_accounts = _store(tmp_path)
    store.create_routing_group(
        name="rotate",
        mode="rotate",
        members=[
            {"target": "openai/Primary/gpt-4o"},
            {"target": "openai/Backup/gpt-4o"},
        ],
    )
    router = RoutingEngine(store, now=_fixed_now)

    first = router.decide("group/rotate")
    second = router.decide("group/rotate")

    assert first.candidates[0].account_name != second.candidates[0].account_name


def test_quota_filter_and_smart_order(tmp_path: Path) -> None:
    store, primary, backup, _claude = _store(tmp_path)
    store.record_quota_snapshot(
        primary["id"],
        window_name="weekly",
        remaining=0,
        limit_value=100,
        unit="requests",
        reset_at="2026-11-16T13:00:00",
    )
    store.record_quota_snapshot(
        backup["id"],
        window_name="weekly",
        remaining=20,
        limit_value=100,
        unit="requests",
        reset_at="2026-11-17T12:00:00",
    )
    store.create_routing_group(
        name="smart",
        mode="smart",
        members=[
            {"target": "openai/Primary/gpt-4o"},
            {"target": "openai/Backup/gpt-4o"},
        ],
    )

    decision = RoutingEngine(store, now=_fixed_now).decide("group/smart")

    assert [candidate.account_name for candidate in decision.candidates] == ["Backup"]


def test_routing_usage_mode_uses_request_log(tmp_path: Path) -> None:
    store, primary, backup, _claude = _store(tmp_path)
    log = GatewayRequestLog(store.path)
    heavy = log.start(model_requested="openai/gpt-4o", stream=False, client=None)
    log.finish(
        heavy["id"],
        status="ok",
        provider="openai",
        account_name="Primary",
        input_tokens=100,
        output_tokens=50,
    )
    store.create_routing_group(
        name="usage",
        mode="usage",
        members=[
            {"target": "openai/Primary/gpt-4o"},
            {"target": "openai/Backup/gpt-4o"},
        ],
    )

    decision = RoutingEngine(store, request_log=log, now=_fixed_now).decide(
        "group/usage"
    )

    assert decision.candidates[0].account_name == "Backup"


def test_routing_rejects_cycles_and_missing_groups(tmp_path: Path) -> None:
    store, *_accounts = _store(tmp_path)
    store.create_routing_group(
        name="a",
        mode="order",
        members=[{"target": "group/b"}],
    )
    store.create_routing_group(
        name="b",
        mode="order",
        members=[{"target": "group/a"}],
    )
    router = RoutingEngine(store, now=_fixed_now)

    with pytest.raises(RoutingError, match="cycle"):
        router.decide("group/a")
    with pytest.raises(RoutingError, match="group not found"):
        router.decide("group/missing")
