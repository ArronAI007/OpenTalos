import json
import sys
from pathlib import Path

import httpx
import pytest

from db import ChatStore
from main import create_app
from media_platform.service import GeneratedMedia, MediaGenerationService, MediaStore
from plugin_platform.store import PluginStore
from runtime import ChatRuntime


class ImageBackend:
    async def generate(self, prompt: str, *, size: str) -> GeneratedMedia:
        return GeneratedMedia(data=b"image", mime_type="image/png", extension="png")


@pytest.fixture
async def m7_api(tmp_path: Path, scripted_client):
    db_path = tmp_path / "chat.db"
    runtime = ChatRuntime(
        ChatStore(db_path),
        model_client=scripted_client(),
        trace_dir=tmp_path / "traces",
    )
    media = MediaGenerationService(
        MediaStore(db_path, tmp_path / "media"),
        image_backend=ImageBackend(),
    )
    app = create_app(
        runtime,
        eval_cases_path=tmp_path / "eval.json",
        media_service=media,
        plugin_store=PluginStore(tmp_path / "plugins"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, tmp_path


async def test_privacy_control_plane_and_audit(m7_api) -> None:
    client, _tmp_path = m7_api
    updated = await client.patch(
        "/api/m7/privacy/settings",
        json={"enabled": True, "fail_closed": True},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True

    rule = await client.post(
        "/api/m7/privacy/rules",
        json={
            "id": "employee_id",
            "title": "Employee ID",
            "pattern": "EMP-[0-9]{6}",
            "action": "mask",
        },
    )
    assert rule.status_code == 201

    tested = await client.post(
        "/api/m7/privacy/test",
        json={"text": "employee EMP-123456", "scope": "api-test"},
    )
    assert tested.status_code == 200
    assert "EMP-123456" not in tested.json()["text"]
    audit = await client.get("/api/m7/privacy/audit")
    assert audit.json()["audit"][0]["rule_id"] == "employee_id"
    assert "EMP-123456" not in json.dumps(audit.json())


async def test_sharing_keys_and_network_warning(m7_api) -> None:
    client, _tmp_path = m7_api
    rejected = await client.put(
        "/api/m7/sharing/config",
        json={"enabled": True, "bind_host": "0.0.0.0"},
    )
    assert rejected.status_code == 400

    config = await client.put(
        "/api/m7/sharing/config",
        json={
            "enabled": True,
            "bind_host": "0.0.0.0",
            "exposure_warning_acknowledged": True,
        },
    )
    assert config.status_code == 200
    key = await client.post(
        "/api/m7/sharing/keys",
        json={"name": "Laptop", "scopes": ["chat.read"]},
    )
    assert key.status_code == 201
    assert key.json()["key"].startswith("otk_")
    assert "key" not in (await client.get("/api/m7/sharing/keys")).json()["keys"][0]


async def test_search_keys_plugins_and_media(m7_api) -> None:
    client, tmp_path = m7_api
    search_key = await client.post(
        "/api/m7/tools/search-keys",
        json={"provider": "tavily", "name": "Primary", "api_key": "secret"},
    )
    assert search_key.status_code == 201
    assert search_key.json()["api_key_masked"]

    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.py").write_text("print('{}')", encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo.plugin",
                "name": "Demo",
                "version": "1.0.0",
                "type": "provider",
                "runtime": "python",
                "entrypoint": [sys.executable, "plugin.py"],
                "capabilities": ["provider.complete"],
            }
        ),
        encoding="utf-8",
    )
    installed = await client.post(
        "/api/m7/plugins/install", json={"source": str(source)}
    )
    assert installed.status_code == 201
    verified = await client.post("/api/m7/plugins/demo.plugin/verify")
    assert verified.json()["ok"] is True

    image = await client.post(
        "/api/m7/media/images",
        json={"prompt": "a cat", "size": "512x512"},
    )
    assert image.status_code == 201
    assert Path(image.json()["path"]).read_bytes() == b"image"
    downloaded = await client.get(f"/api/m7/media/files/{image.json()['job_id']}")
    assert downloaded.status_code == 200
    assert downloaded.content == b"image"
