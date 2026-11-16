import json
from pathlib import Path

import pytest

from agent_platform.catalog import AgentDefinition
from agent_platform.config import AgentConfigError, AgentConfigManager
from agent_platform.store import AgentPlatformStore


def _definition(tmp_path: Path, config_format: str = "json-env") -> AgentDefinition:
    return AgentDefinition(
        id="demo",
        name="Demo Agent",
        commands=("demo",),
        config_paths={"darwin": (str(tmp_path / "settings.json"),)},
        config_format=config_format,
        compatibility="native",
        compatibility_path="Native adapter",
        install_hint="npm install -g demo",
        update_plan={},
        resource_paths={},
        catalog_source="test",
    )


def test_json_config_preview_and_apply_preserve_user_keys(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"theme": "dark", "env": {"KEEP": "yes"}}, indent=4) + "\n",
        encoding="utf-8",
    )
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    definition = _definition(tmp_path)

    preview = manager.preview(definition, model="group/coding")

    assert preview["changed"] is True
    assert "group/coding" in preview["after"]

    result = manager.apply(definition, model="group/coding")
    payload = json.loads(config.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert payload["theme"] == "dark"
    assert payload["env"]["KEEP"] == "yes"
    assert payload["env"]["ANTHROPIC_MODEL"] == "group/coding"
    assert payload["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:3425/v1"
    assert payload["env"]["ANTHROPIC_AUTH_TOKEN"] == "opentalos-local"


def test_codex_toml_updates_top_level_model_and_provider_block(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    config.write_text(
        'approval_policy = "never"\nmodel = "old"\n\n[features]\nweb_search = true\n',
        encoding="utf-8",
    )
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    definition = _definition(tmp_path, config_format="codex-toml")

    manager.apply(definition, model="group/coding")
    rendered = config.read_text(encoding="utf-8")

    assert 'approval_policy = "never"' in rendered
    assert 'model = "group/coding"' in rendered
    assert 'model_provider = "opentalos"' in rendered
    assert "[features]" in rendered
    assert "[model_providers.opentalos]" in rendered
    assert 'base_url = "http://127.0.0.1:3425/v1"' in rendered


def test_failed_atomic_replace_rolls_back_without_partial_write(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    original = b'{"theme": "dark"}\n'
    config.write_bytes(original)
    store = AgentPlatformStore(tmp_path / "platform.db")

    def fail_replace(_source, _destination):
        raise OSError("disk full")

    manager = AgentConfigManager(
        store,
        gateway_url="http://127.0.0.1:3425/v1",
        replace=fail_replace,
    )

    with pytest.raises(AgentConfigError, match="disk full"):
        manager.apply(_definition(tmp_path), model="group/coding")

    assert config.read_bytes() == original
    transactions = store.list_transactions("demo")
    assert transactions[0]["status"] == "failed"


def test_restore_recovers_exact_original_bytes_and_removes_created_file(
    tmp_path: Path,
) -> None:
    config = tmp_path / "settings.json"
    original = b'{\n  "theme": "dark"\n}\n'
    config.write_bytes(original)
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    definition = _definition(tmp_path)

    manager.apply(definition, model="group/coding")
    manager.restore("demo")

    assert config.read_bytes() == original

    created_config = tmp_path / "created.json"
    created_definition = AgentDefinition(
        **{
            **definition.__dict__,
            "id": "created",
            "config_paths": {"darwin": (str(created_config),)},
        }
    )
    manager.apply(created_definition, model="group/coding")
    assert created_config.exists()
    manager.restore("created")
    assert created_config.exists() is False


def test_library_instructions_use_managed_block_without_removing_user_content(
    tmp_path: Path,
) -> None:
    config = tmp_path / "settings.json"
    instructions = tmp_path / "AGENTS.md"
    config.write_text("{}\n", encoding="utf-8")
    instructions.write_text("# User instructions\n\nKeep me.\n", encoding="utf-8")
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    base = _definition(tmp_path)
    definition = AgentDefinition(
        **{
            **base.__dict__,
            "resource_paths": {"instructions": str(instructions)},
        }
    )
    item = store.create_library_item(
        kind="instructions",
        name="Team rules",
        content="Always run tests.",
    )

    applied = manager.apply_library_item(definition, item)
    rendered = instructions.read_text(encoding="utf-8")

    assert applied["path"] == str(instructions)
    assert "Keep me." in rendered
    assert "Always run tests." in rendered
    assert "BEGIN OPENTALOS" in rendered

    manager.remove_library_item(definition, item["id"])
    assert instructions.read_text(encoding="utf-8") == "# User instructions\n\nKeep me.\n"


def test_library_mcp_server_is_merged_and_removed_from_json(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    config.write_text('{"owned": true}\n', encoding="utf-8")
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    definition = _definition(tmp_path)
    item = store.create_library_item(
        kind="mcp",
        name="docs",
        content="",
        metadata={"command": "docs-mcp", "args": ["--stdio"]},
    )

    manager.apply_library_item(definition, item)
    payload = json.loads(config.read_text(encoding="utf-8"))

    assert payload["owned"] is True
    key = next(iter(payload["mcpServers"]))
    assert key.startswith("opentalos-docs-")
    assert payload["mcpServers"][key]["command"] == "docs-mcp"

    manager.remove_library_item(definition, item["id"])
    assert json.loads(config.read_text(encoding="utf-8")) == {"owned": True}


def test_library_command_is_written_to_a_namespaced_native_file(
    tmp_path: Path,
) -> None:
    config = tmp_path / "settings.json"
    config.write_text("{}\n", encoding="utf-8")
    store = AgentPlatformStore(tmp_path / "platform.db")
    manager = AgentConfigManager(store, gateway_url="http://127.0.0.1:3425/v1")
    base = _definition(tmp_path)
    definition = AgentDefinition(
        **{
            **base.__dict__,
            "resource_paths": {
                "commands": str(tmp_path / "commands" / "{name}.md")
            },
        }
    )
    item = store.create_library_item(
        kind="commands",
        name="review-pr",
        content="Review the current pull request.",
    )

    manager.apply_library_item(definition, item)

    target = tmp_path / "commands" / "review-pr.md"
    assert target.read_text(encoding="utf-8") == "Review the current pull request."
    manager.remove_library_item(definition, item["id"])
    assert not target.exists()
