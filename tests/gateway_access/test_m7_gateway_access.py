from pathlib import Path

import pytest

from gateway_access.store import (
    GatewayAccessDeniedError,
    GatewayAccessStore,
    GatewayBudgetError,
)


def test_named_keys_rotate_revoke_and_never_store_plaintext(tmp_path: Path) -> None:
    store = GatewayAccessStore(tmp_path / "access.db")
    created = store.create_key(
        name="Alice laptop",
        scopes=["chat.read", "models.read"],
        allowed_models=["group/coding", "openai/*"],
    )

    assert created["key"].startswith("otk_")
    assert "key" not in store.list_keys()[0]
    principal = store.authenticate(f"Bearer {created['key']}")
    assert principal["name"] == "Alice laptop"

    rotated = store.rotate_key(created["id"])
    with pytest.raises(GatewayAccessDeniedError):
        store.authenticate(f"Bearer {created['key']}")
    assert store.authenticate(f"Bearer {rotated['key']}")["id"] == created["id"]

    store.revoke_key(created["id"])
    with pytest.raises(GatewayAccessDeniedError):
        store.authenticate(f"Bearer {rotated['key']}")
    assert {"rotate", "revoke"} <= {item["action"] for item in store.list_audit()}


def test_key_model_access_and_budget_are_enforced(tmp_path: Path) -> None:
    store = GatewayAccessStore(tmp_path / "access.db")
    created = store.create_key(
        name="Limited",
        scopes=["chat.read"],
        allowed_models=["openai/*"],
        daily_requests=1,
        concurrency_limit=1,
    )
    principal = store.authenticate(f"Bearer {created['key']}")

    reservation = store.reserve(
        principal,
        model="openai/gpt-5",
        account_id="account-1",
    )
    with pytest.raises(GatewayBudgetError, match="concurrency"):
        store.reserve(
            principal,
            model="openai/gpt-5",
            account_id="account-1",
        )
    store.settle(
        reservation,
        status="ok",
        input_tokens=100,
        output_tokens=50,
        cost_micros=2500,
    )
    with pytest.raises(GatewayBudgetError, match="daily"):
        store.reserve(
            principal,
            model="openai/gpt-5",
            account_id="account-1",
        )

    with pytest.raises(GatewayAccessDeniedError, match="model"):
        store.reserve(
            principal,
            model="anthropic/claude",
            account_id="account-1",
        )


def test_read_only_and_admin_scopes_are_distinct(tmp_path: Path) -> None:
    store = GatewayAccessStore(tmp_path / "access.db")
    created = store.create_key(
        name="Reader",
        scopes=["models.read"],
        read_only=True,
    )
    principal = store.authenticate(f"Bearer {created['key']}")

    store.require(principal, scope="models.read")
    with pytest.raises(GatewayAccessDeniedError, match="chat.read"):
        store.require(principal, scope="chat.read")
    with pytest.raises(GatewayAccessDeniedError, match="admin"):
        store.require(principal, scope="admin")


def test_sharing_config_requires_explicit_exposure_acknowledgement(tmp_path: Path) -> None:
    store = GatewayAccessStore(tmp_path / "access.db")

    with pytest.raises(ValueError, match="warning"):
        store.update_sharing(enabled=True, bind_host="0.0.0.0")

    config = store.update_sharing(
        enabled=True,
        bind_host="0.0.0.0",
        exposure_warning_acknowledged=True,
    )
    assert config["enabled"] is True
    assert config["warning"].startswith("Gateway")
