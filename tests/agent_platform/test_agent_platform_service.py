from pathlib import Path

from agent_platform.catalog import AgentDefinition
from agent_platform.service import AgentPlatformService
from agent_platform.store import AgentPlatformStore
from model_platform.control_plane import ControlPlaneStore


def _definition(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        id="demo",
        name="Demo",
        commands=("demo",),
        config_paths={"darwin": (str(tmp_path / "config.toml"),)},
        config_format="codex-toml",
        compatibility="native",
        compatibility_path="Native",
        install_hint="brew install demo",
        update_plan={
            "npm": ("npm", "install", "-g", "demo@latest"),
            "brew": ("brew", "upgrade", "demo"),
        },
        resource_paths={},
        catalog_source="test",
    )


def test_update_plan_matches_homebrew_installation(tmp_path: Path) -> None:
    store = AgentPlatformStore(tmp_path / "platform.db")
    store.save_installations(
        [
            {
                "agent_id": "demo",
                "name": "Demo",
                "installed": True,
                "version": "1.0.0",
                "install_path": "/opt/homebrew/bin/demo",
                "install_source": "command",
                "config_path": None,
                "platform": "darwin",
                "compatibility": "native",
                "compatibility_path": "Native",
                "install_hint": "brew install demo",
            }
        ]
    )
    service = AgentPlatformService(
        store,
        ControlPlaneStore(store.path),
        catalog=[_definition(tmp_path)],
        command_runner=lambda command: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "updated\n"},
        )(),
    )

    plan = service.update_plan("demo")
    updated = service.execute_update("demo")

    assert plan["update_method"] == "brew"
    assert plan["command"] == ["brew", "upgrade", "demo"]
    assert updated["status"] == "ok"
