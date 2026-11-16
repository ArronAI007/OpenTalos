from pathlib import Path

import pytest

from model_platform.control_plane import ControlPlaneStore, ControlPlaneValidationError
from model_platform.discovery import ModelDescriptor
from model_platform.presets import list_presets


def test_core_provider_presets_are_available() -> None:
    presets = {preset.id: preset for preset in list_presets()}

    assert {"anthropic", "openai", "deepseek", "moonshot", "openai-compatible"} <= set(
        presets
    )
    assert presets["openai"].backend == "openai-compatible"
    assert presets["anthropic"].backend == "anthropic"


def test_account_crud_masks_keys_and_preserves_proxy(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")
    created = store.create_account(
        provider="deepseek",
        name="Work",
        backend="openai-compatible",
        base_url="https://api.deepseek.com",
        api_key="sk-secret-1234",
        proxy_url="http://127.0.0.1:7890",
    )

    assert created["api_key_masked"].endswith("1234")
    assert "secret" not in created["api_key_masked"]
    assert created["proxy_url"] == "http://127.0.0.1:7890"
    assert "api_key" not in created

    updated = store.update_account(created["id"], name="DeepSeek Work", enabled=False)
    assert updated is not None
    assert updated["name"] == "DeepSeek Work"
    assert updated["enabled"] is False

    assert [account["id"] for account in store.list_accounts()] == [created["id"]]
    assert store.delete_account(created["id"]) is True
    assert store.list_accounts() == []


def test_account_validation_rejects_unsafe_urls_and_duplicate_names(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")

    with pytest.raises(ControlPlaneValidationError, match="base_url"):
        store.create_account(
            provider="custom",
            name="Bad",
            backend="openai-compatible",
            base_url="file:///tmp/key",
            api_key="secret",
        )

    store.create_account(
        provider="openai",
        name="Primary",
        backend="openai-compatible",
        api_key="secret",
    )
    with pytest.raises(ControlPlaneValidationError, match="already exists"):
        store.create_account(
            provider="openai",
            name="Primary",
            backend="openai-compatible",
            api_key="another",
        )


def test_model_registry_replace_filters_and_updates_count(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")
    account = store.create_account(
        provider="openai",
        name="Primary",
        backend="openai-compatible",
        api_key="secret",
    )

    store.replace_models(
        account["id"],
        [
            ModelDescriptor(
                model_id="gpt-4o",
                display_name="GPT-4o",
                protocol="openai-chat",
                context_window=128000,
                supports_tools=True,
                supports_thinking=False,
                source="provider",
            ),
            ModelDescriptor(
                model_id="gpt-4o-mini",
                display_name="GPT-4o mini",
                protocol="openai-chat",
                context_window=None,
                supports_tools=True,
                supports_thinking=False,
                source="provider",
            ),
        ],
    )

    assert len(store.list_models(account_id=account["id"])) == 2
    assert [model["model_id"] for model in store.list_models(query="mini")] == [
        "gpt-4o-mini"
    ]
    refreshed = store.get_account(account["id"])
    assert refreshed is not None
    assert refreshed["model_count"] == 2


def test_import_legacy_provider_configs_is_idempotent(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")
    legacy = [
        {
            "name": "Legacy OpenAI",
            "purpose": "chat",
            "backend": "openai-compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-legacy",
            "model_name": "gpt-4o",
        },
        {
            "name": "Legacy Embedding",
            "purpose": "embedding",
            "backend": None,
            "base_url": None,
            "api_key": "embed-key",
            "model_name": "text-embedding-3-small",
        },
    ]

    first = store.import_legacy_configs(legacy)
    second = store.import_legacy_configs(legacy)

    assert first == 1
    assert second == 0
    assert store.list_accounts()[0]["name"] == "Legacy OpenAI"
    assert store.list_models()[0]["model_id"] == "gpt-4o"


def test_profiles_store_named_control_plane_snapshots(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")
    created = store.save_profile(
        "Coding",
        {"active_accounts": ["a"], "preferred_models": ["openai/gpt-4o"]},
    )

    assert created["name"] == "Coding"
    assert store.list_profiles()[0]["payload"]["preferred_models"] == [
        "openai/gpt-4o"
    ]
    assert store.delete_profile(created["id"]) is True
