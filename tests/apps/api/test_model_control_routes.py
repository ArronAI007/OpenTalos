from pathlib import Path

import httpx
import pytest

from db import ChatStore
from main import create_app
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor
from runtime import ChatRuntime


class FakeDiscovery:
    async def discover(self, _account) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                model_id="gpt-4o",
                display_name="GPT-4o",
                protocol="openai-chat",
                context_window=128000,
                supports_tools=True,
                supports_thinking=False,
                source="provider",
            )
        ]


@pytest.fixture
async def control_api(tmp_path: Path, scripted_client):
    db_path = tmp_path / "chat.db"
    runtime = ChatRuntime(
        ChatStore(db_path),
        model_client=scripted_client(),
        trace_dir=tmp_path / "traces",
    )
    app = create_app(
        runtime,
        eval_cases_path=tmp_path / "eval_cases.json",
        model_control_store=ControlPlaneStore(db_path),
        model_discovery=FakeDiscovery(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_control_plane_lists_presets(control_api) -> None:
    response = await control_api.get("/api/model-control/presets")

    assert response.status_code == 200
    presets = {preset["id"]: preset for preset in response.json()["presets"]}
    assert presets["openai"]["backend"] == "openai-compatible"
    assert presets["anthropic"]["backend"] == "anthropic"


async def test_control_plane_account_crud_and_model_discovery(control_api) -> None:
    created_response = await control_api.post(
        "/api/model-control/accounts",
        json={
            "provider": "openai",
            "name": "Primary",
            "backend": "openai-compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-secret-1234",
            "proxy_url": "http://127.0.0.1:7890",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["api_key_masked"].endswith("1234")
    assert "api_key" not in created

    discovered = await control_api.post(
        f"/api/model-control/accounts/{created['id']}/discover"
    )
    assert discovered.status_code == 200
    assert discovered.json()["models"][0]["model_id"] == "gpt-4o"

    listed = await control_api.get(
        "/api/model-control/models", params={"account_id": created["id"]}
    )
    assert listed.json()["models"][0]["display_name"] == "GPT-4o"

    updated = await control_api.patch(
        f"/api/model-control/accounts/{created['id']}",
        json={"enabled": False, "name": "Primary account"},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = await control_api.delete(
        f"/api/model-control/accounts/{created['id']}"
    )
    assert deleted.status_code == 204
    assert (await control_api.get("/api/model-control/accounts")).json()["accounts"] == []


async def test_control_plane_rejects_invalid_proxy_url(control_api) -> None:
    response = await control_api.post(
        "/api/model-control/accounts",
        json={
            "provider": "openai",
            "name": "Bad proxy",
            "backend": "openai-compatible",
            "api_key": "secret",
            "proxy_url": "file:///tmp/proxy",
        },
    )

    assert response.status_code == 400
    assert "proxy_url" in response.json()["detail"]


async def test_control_plane_imports_legacy_provider_configs(control_api) -> None:
    legacy = await control_api.post(
        "/api/providers",
        json={
            "name": "Legacy OpenAI",
            "purpose": "chat",
            "backend": "openai-compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-legacy",
            "model_name": "gpt-4o",
        },
    )
    assert legacy.status_code == 200

    imported = await control_api.post("/api/model-control/imports/legacy")
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    accounts = (await control_api.get("/api/model-control/accounts")).json()["accounts"]
    assert accounts[0]["name"] == "Legacy OpenAI"
    assert accounts[0]["model_count"] == 1


async def test_control_plane_profiles(control_api) -> None:
    created = await control_api.post(
        "/api/model-control/profiles",
        json={"name": "Coding", "payload": {"preferred_models": ["openai/gpt-4o"]}},
    )

    assert created.status_code == 201
    listed = await control_api.get("/api/model-control/profiles")
    assert listed.json()["profiles"][0]["name"] == "Coding"
    deleted = await control_api.delete(
        f"/api/model-control/profiles/{created.json()['id']}"
    )
    assert deleted.status_code == 204


async def test_control_plane_routing_groups(control_api) -> None:
    created = await control_api.post(
        "/api/model-control/routing-groups",
        json={
            "name": "coding",
            "mode": "order",
            "sticky": True,
            "members": [
                {"target": "openai/gpt-4o", "weight": 1},
                {"target": "group/backup", "weight": 2},
            ],
        },
    )

    assert created.status_code == 201
    group = created.json()
    assert group["name"] == "coding"
    listed = await control_api.get("/api/model-control/routing-groups")
    assert listed.json()["groups"][0]["members"][1]["weight"] == 2

    updated = await control_api.patch(
        f"/api/model-control/routing-groups/{group['id']}",
        json={"mode": "smart", "members": [{"target": "openai/gpt-4o"}]},
    )
    assert updated.status_code == 200
    assert updated.json()["mode"] == "smart"
    assert len(updated.json()["members"]) == 1

    deleted = await control_api.delete(
        f"/api/model-control/routing-groups/{group['id']}"
    )
    assert deleted.status_code == 204


async def test_control_plane_quota_and_usage_routes(control_api) -> None:
    account = (
        await control_api.post(
            "/api/model-control/accounts",
            json={
                "provider": "openai",
                "name": "Primary",
                "backend": "openai-compatible",
                "api_key": "secret",
            },
        )
    ).json()
    quota = await control_api.post(
        "/api/model-control/quotas",
        json={
            "account_id": account["id"],
            "window_name": "weekly",
            "remaining": 77,
            "limit_value": 100,
            "unit": "requests",
            "reset_at": "2026-11-20T00:00:00",
        },
    )
    assert quota.status_code == 201
    listed = await control_api.get(
        "/api/model-control/quotas", params={"account_id": account["id"]}
    )
    assert listed.json()["quotas"][0]["remaining"] == 77

    usage = await control_api.get("/api/model-control/usage")
    assert usage.status_code == 200
    assert usage.json()["total_tokens"] == 0
