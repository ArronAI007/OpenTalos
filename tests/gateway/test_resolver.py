from pathlib import Path

import pytest

from gateway.resolver import ModelResolutionError, ModelResolver
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor


def _store(tmp_path: Path) -> tuple[ControlPlaneStore, dict, dict]:
    store = ControlPlaneStore(tmp_path / "control.db")
    primary = store.create_account(
        provider="openai",
        name="Primary",
        backend="openai-compatible",
        base_url="https://api.openai.com/v1",
        api_key="sk-primary",
    )
    secondary = store.create_account(
        provider="anthropic",
        name="Claude",
        backend="anthropic",
        api_key="anthropic-key",
    )
    store.replace_models(
        primary["id"],
        [
            ModelDescriptor(
                "gpt-4o",
                "GPT-4o",
                "openai-chat",
                128000,
                True,
                False,
                "provider",
            )
        ],
    )
    store.replace_models(
        secondary["id"],
        [
            ModelDescriptor(
                "claude-sonnet-5",
                "Claude Sonnet 5",
                "anthropic-messages",
                200000,
                True,
                True,
                "provider",
            )
        ],
    )
    return store, primary, secondary


def test_resolver_accepts_bare_and_provider_qualified_models(tmp_path: Path) -> None:
    store, primary, secondary = _store(tmp_path)
    resolver = ModelResolver(store)

    bare = resolver.resolve("gpt-4o")
    qualified = resolver.resolve("anthropic/claude-sonnet-5")

    assert bare.account_id == primary["id"]
    assert bare.model_id == "gpt-4o"
    assert bare.backend == "openai-compatible"
    assert bare.api_key == "sk-primary"
    assert qualified.account_id == secondary["id"]
    assert qualified.backend == "anthropic"


def test_resolver_prefers_provider_prefix_when_model_is_not_catalogued(
    tmp_path: Path,
) -> None:
    store, primary, _secondary = _store(tmp_path)
    resolved = ModelResolver(store).resolve("openai/gpt-new")

    assert resolved.account_id == primary["id"]
    assert resolved.model_id == "gpt-new"


def test_resolver_ignores_disabled_accounts_and_reports_unknown_models(
    tmp_path: Path,
) -> None:
    store, primary, _secondary = _store(tmp_path)
    store.update_account(primary["id"], enabled=False)
    resolver = ModelResolver(store)

    with pytest.raises(ModelResolutionError, match="no enabled account"):
        resolver.resolve("openai/gpt-4o")


def test_resolver_rejects_ambiguous_bare_models(tmp_path: Path) -> None:
    store = ControlPlaneStore(tmp_path / "control.db")
    for name in ("A", "B"):
        account = store.create_account(
            provider="openai",
            name=name,
            backend="openai-compatible",
            base_url="https://example.test/v1",
            api_key=f"key-{name}",
        )
        store.replace_models(
            account["id"],
            [
                ModelDescriptor(
                    "same-model",
                    "Same model",
                    "openai-chat",
                    None,
                    True,
                    False,
                    "provider",
                )
            ],
        )

    with pytest.raises(ModelResolutionError, match="ambiguous"):
        ModelResolver(store).resolve("same-model")
