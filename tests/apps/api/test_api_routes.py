import json

import httpx
import pytest
from core.protocol import ToolCompletion
from db import ChatStore
from main import create_app
from runtime import ChatRuntime


@pytest.fixture
def api(tmp_path, scripted_client):
    client = scripted_client(tool_completions=[
        ToolCompletion(text="pong", requested_tools=[], model_id="mock-model"),
    ])
    # scripted_client 的 mock 客户端会先读 .env 里的 MODEL_NAME（core/model.py 的 load_dotenv
    # + "mock 默认值仅在环境变量为空时兜底"），导致 model_name 泄漏成真实模型名。测试里强制回
    # 确定性 mock 名，与 ToolCompletion(model_id="mock-model") 的意图一致。
    client.model_name = "mock-model"
    runtime = ChatRuntime(
        ChatStore(tmp_path / "chat.db"),
        model_client=client,
        skill_service_url="http://127.0.0.1:1",
        trace_dir=tmp_path / "traces",
    )
    app = create_app(runtime)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_config_reports_mock_model(api) -> None:
    resp = await api.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_name"] == "mock-model"
    assert "react" in body["agent_types"]


async def test_task_lifecycle(api) -> None:
    resp = await api.post("/api/tasks", json={"agent_type": "react"})
    assert resp.status_code == 201
    task = resp.json()
    assert (await api.get("/api/tasks")).json()["tasks"][0]["id"] == task["id"]
    assert (await api.delete(f"/api/tasks/{task['id']}")).status_code == 204
    assert (await api.get("/api/tasks")).json()["tasks"] == []


async def test_post_invalid_agent_type_422(api) -> None:
    resp = await api.post("/api/tasks", json={"agent_type": "nope"})
    assert resp.status_code == 422


async def test_message_sse_flow_and_persistence(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    async with api.stream("POST", f"/api/tasks/{task['id']}/messages", json={"content": "ping"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = (await resp.aread()).decode()
    frames = [block for block in body.split("\n\n") if block.strip()]
    events = [json.loads(frame.strip().removeprefix("data: ")) for frame in frames]
    assert events[0]["type"] == "delta"
    assert events[-1] == {"type": "done", "reply": "pong"}
    rows = (await api.get(f"/api/tasks/{task['id']}/messages")).json()["messages"]
    assert [r["kind"] for r in rows] == ["user", "assistant"]


async def test_message_on_missing_task_404(api) -> None:
    resp = await api.post("/api/tasks/nope/messages", json={"content": "x"})
    assert resp.status_code == 404


async def test_skills_proxy_degrades_when_unreachable(api) -> None:
    resp = await api.get("/api/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is False
    assert body["skills"] == []


async def test_cors_origins_configurable_via_env(api, monkeypatch, tmp_path, scripted_client) -> None:
    preflight_headers = {"Access-Control-Request-Method": "POST"}

    # 默认收紧：未设 CORS_ORIGINS 的现有 fixture 拒绝 :3010 跨源预检。
    resp = await api.options(
        "/api/tasks", headers={"Origin": "http://localhost:3010", **preflight_headers}
    )
    assert "access-control-allow-origin" not in resp.headers

    # 设 env 后重新 create_app 建独立实例，不污染共享 fixture。
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3010,http://localhost:3000")
    client = scripted_client(tool_completions=[
        ToolCompletion(text="pong", requested_tools=[], model_id="mock-model"),
    ])
    client.model_name = "mock-model"
    runtime = ChatRuntime(
        ChatStore(tmp_path / "chat.db"),
        model_client=client,
        skill_service_url="http://127.0.0.1:1",
        trace_dir=tmp_path / "traces",
    )
    custom = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    )

    # 列出的源 :3010 放行。
    resp = await custom.options(
        "/api/tasks", headers={"Origin": "http://localhost:3010", **preflight_headers}
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3010"

    # 未列出的源被拒之门外。
    resp = await custom.options(
        "/api/tasks", headers={"Origin": "http://evil.example", **preflight_headers}
    )
    assert "access-control-allow-origin" not in resp.headers
