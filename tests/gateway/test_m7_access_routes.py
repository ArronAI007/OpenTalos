from pathlib import Path

import httpx
import pytest

from apps.gateway.main import create_app
from gateway.service import GatewayService
from gateway_access.store import GatewayAccessStore
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor


@pytest.fixture
async def protected_gateway(tmp_path: Path):
    db_path = tmp_path / "gateway.db"
    control = ControlPlaneStore(db_path)
    account = control.create_account(
        provider="mock",
        name="Local",
        backend="mock",
        api_key="local",
    )
    control.replace_models(
        account["id"],
        [
            ModelDescriptor(
                "mock-model",
                "Mock",
                "openai-chat",
                32000,
                True,
                False,
                "manual",
            )
        ],
    )
    access = GatewayAccessStore(db_path)
    access.update_sharing(
        enabled=True,
        bind_host="127.0.0.1",
        exposure_warning_acknowledged=True,
    )
    key = access.create_key(
        name="Test client",
        scopes=["chat.read"],
        allowed_models=["mock/*"],
        daily_requests=1,
    )
    app = create_app(GatewayService(control), access_store=access)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app,
            client=("203.0.113.10", 12345),
        ),
        base_url="http://test",
    ) as client:
        yield client, key["key"]


async def test_gateway_requires_named_key_and_scope(protected_gateway) -> None:
    client, key = protected_gateway

    missing = await client.post(
        "/v1/chat/completions",
        json={
            "model": "mock/mock-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert missing.status_code == 403

    allowed = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "mock/mock-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert allowed.status_code == 200

    denied_scope = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {key}"}
    )
    assert denied_scope.status_code == 403


async def test_gateway_key_daily_budget_and_model_acl(protected_gateway) -> None:
    client, key = protected_gateway

    denied_model = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "openai/gpt-5",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert denied_model.status_code == 403

    first = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "mock/mock-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert first.status_code == 200
    second = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "mock/mock-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert second.status_code == 429
