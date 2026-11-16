from pathlib import Path

import httpx
import pytest

from agent_platform.catalog import AgentDefinition
from agent_platform.service import AgentPlatformService
from agent_platform.store import AgentPlatformStore
from db import ChatStore
from main import create_app
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor
from runtime import ChatRuntime


def _definition(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        id="codex",
        name="Codex",
        commands=("codex",),
        config_paths={"darwin": (str(tmp_path / "codex.toml"),)},
        config_format="codex-toml",
        compatibility="native",
        compatibility_path="Native Codex TOML adapter",
        install_hint="npm install -g @openai/codex",
        update_plan={"npm": ("npm", "install", "-g", "@openai/codex@latest")},
        resource_paths={},
        catalog_source="test",
    )


@pytest.fixture
async def agent_platform_api(tmp_path: Path, scripted_client):
    db_path = tmp_path / "chat.db"
    runtime = ChatRuntime(
        ChatStore(db_path),
        model_client=scripted_client(),
        trace_dir=tmp_path / "traces",
    )
    control_store = ControlPlaneStore(db_path)
    account = control_store.create_account(
        provider="openai",
        name="Work",
        backend="openai-compatible",
        api_key="secret",
    )
    control_store.replace_models(
        account["id"],
        [
            ModelDescriptor(
                model_id="gpt-5",
                display_name="GPT-5",
                protocol="openai-chat",
                context_window=200000,
                supports_tools=True,
                supports_thinking=True,
                source="provider",
            )
        ],
    )
    platform_store = AgentPlatformStore(db_path)
    service = AgentPlatformService(
        platform_store,
        control_store,
        catalog=[_definition(tmp_path)],
        gateway_url="http://127.0.0.1:3421/v1",
    )
    service.discovery = type(
        "Discovery",
        (),
        {
            "discover": lambda self, agent_id=None: [
                {
                    "agent_id": "codex",
                    "name": "Codex",
                    "installed": True,
                    "version": "1.2.3",
                    "install_path": "/usr/local/bin/codex",
                    "install_source": "command",
                    "config_path": str(tmp_path / "codex.toml"),
                    "platform": "darwin",
                    "compatibility": "native",
                    "compatibility_path": "Native Codex TOML adapter",
                }
            ]
        },
    )()
    app = create_app(
        runtime,
        eval_cases_path=tmp_path / "eval_cases.json",
        model_control_store=control_store,
        agent_platform_service=service,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_agent_platform_catalog_discovery_and_model_picker(
    agent_platform_api,
) -> None:
    catalog = await agent_platform_api.get("/api/agent-platform/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["agents"][0]["id"] == "codex"

    discovered = await agent_platform_api.post("/api/agent-platform/discover")
    assert discovered.json()["agents"][0]["version"] == "1.2.3"

    models = await agent_platform_api.get(
        "/api/agent-platform/agents/codex/models"
    )
    assert models.status_code == 200
    option = models.json()["models"][0]
    assert option["value"] == "openai/Work/gpt-5"
    assert option["eligible"] is True


async def test_agent_platform_binding_configure_preview_and_restore(
    agent_platform_api,
    tmp_path: Path,
) -> None:
    binding = await agent_platform_api.patch(
        "/api/agent-platform/agents/codex/binding",
        json={
            "model": "openai/Work/gpt-5",
            "shortlist": ["openai/Work/gpt-5"],
            "routing_preference": "openai/Work/gpt-5",
        },
    )
    assert binding.status_code == 200

    preview = await agent_platform_api.post(
        "/api/agent-platform/agents/codex/configuration/preview"
    )
    assert preview.status_code == 200
    assert preview.json()["changed"] is True

    applied = await agent_platform_api.post(
        "/api/agent-platform/agents/codex/configuration/apply"
    )
    assert applied.status_code == 200
    assert (tmp_path / "codex.toml").exists()

    restored = await agent_platform_api.post(
        "/api/agent-platform/agents/codex/restore"
    )
    assert restored.status_code == 200
    assert (tmp_path / "codex.toml").exists() is False


async def test_agent_platform_profile_round_trip(agent_platform_api) -> None:
    await agent_platform_api.patch(
        "/api/agent-platform/agents/codex/binding",
        json={"model": "openai/Work/gpt-5", "shortlist": ["openai/Work/gpt-5"]},
    )
    saved = await agent_platform_api.post(
        "/api/agent-platform/profiles", json={"name": "Work"}
    )
    assert saved.status_code == 201

    await agent_platform_api.patch(
        "/api/agent-platform/agents/codex/binding",
        json={"model": "", "shortlist": []},
    )
    restored = await agent_platform_api.post(
        f"/api/agent-platform/profiles/{saved.json()['id']}/apply"
    )
    assert restored.status_code == 200
    assert restored.json()["bindings"]["codex"]["model"] == "openai/Work/gpt-5"


async def test_agent_platform_update_plan_and_library_lifecycle(
    agent_platform_api,
    tmp_path: Path,
) -> None:
    plan = await agent_platform_api.get(
        "/api/agent-platform/agents/codex/update-plan"
    )
    assert plan.status_code == 200
    assert plan.json()["automatic"] is True

    created = await agent_platform_api.post(
        "/api/agent-platform/library",
        json={"kind": "skills", "name": "review", "content": "# Review\n"},
    )
    assert created.status_code == 201
    item = created.json()

    applied = await agent_platform_api.post(
        f"/api/agent-platform/agents/codex/library/{item['id']}/apply"
    )
    assert applied.status_code == 400
    assert "does not support" in applied.json()["detail"]

    deleted = await agent_platform_api.delete(
        f"/api/agent-platform/library/{item['id']}"
    )
    assert deleted.status_code == 204
