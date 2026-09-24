import json

import httpx
import pytest
from core.protocol import ToolCompletion
from db import ChatStore
from main import _sse, create_app
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


async def test_patch_task_rename_persists(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"title": "  重命名任务  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == task["id"]
    assert body["title"] == "重命名任务"  # 已去首尾空白
    # 持久化：列表里仍是新标题
    assert (await api.get("/api/tasks")).json()["tasks"][0]["title"] == "重命名任务"


async def test_patch_task_missing_404(api) -> None:
    resp = await api.patch("/api/tasks/no-such-id", json={"title": "x"})
    assert resp.status_code == 404


async def test_patch_task_blank_title_400(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    assert (await api.patch(f"/api/tasks/{task['id']}", json={"title": ""})).status_code == 400
    assert (await api.patch(f"/api/tasks/{task['id']}", json={"title": "   "})).status_code == 400


async def test_patch_task_empty_body_422(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    assert (await api.patch(f"/api/tasks/{task['id']}", json={})).status_code == 422


async def test_patch_task_pin_and_unpin(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"pinned": True})
    assert resp.status_code == 200
    assert resp.json()["pinned"] == 1
    # 列表里同样体现已固定
    assert (await api.get("/api/tasks")).json()["tasks"][0]["pinned"] == 1
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"pinned": False})
    assert resp.status_code == 200
    assert resp.json()["pinned"] == 0
    assert (await api.get("/api/tasks")).json()["tasks"][0]["pinned"] == 0


async def test_list_tasks_places_pinned_first(api) -> None:
    pinned = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{pinned['id']}", json={"pinned": True})
    assert resp.status_code == 200
    newer = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    # 固定任务 updated_at 更旧仍排在最前
    ids = [t["id"] for t in (await api.get("/api/tasks")).json()["tasks"]]
    assert ids == [pinned["id"], newer["id"]]


async def test_patch_task_star_and_unstar(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"starred": True})
    assert resp.status_code == 200
    assert resp.json()["starred"] == 1
    # 列表里同样体现已收藏
    assert (await api.get("/api/tasks")).json()["tasks"][0]["starred"] == 1
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"starred": False})
    assert resp.status_code == 200
    assert resp.json()["starred"] == 0
    assert (await api.get("/api/tasks")).json()["tasks"][0]["starred"] == 0


async def test_list_tasks_orders_pinned_starred_plain(api) -> None:
    starred = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    assert (await api.patch(f"/api/tasks/{starred['id']}", json={"starred": True})).status_code == 200
    pinned = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    assert (await api.patch(f"/api/tasks/{pinned['id']}", json={"pinned": True})).status_code == 200
    plain = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    # 固定最前、收藏次之、普通最后（收藏任务的 updated_at 最旧仍排在普通之前）
    ids = [t["id"] for t in (await api.get("/api/tasks")).json()["tasks"]]
    assert ids == [pinned["id"], starred["id"], plain["id"]]


async def test_patch_task_archive_hides_from_main_list(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"archived": True})
    assert resp.status_code == 200
    assert resp.json()["archived"] == 1
    # 主列表消失，归档列表出现
    assert (await api.get("/api/tasks")).json()["tasks"] == []
    archived = (await api.get("/api/tasks", params={"archived": 1})).json()["tasks"]
    assert [t["id"] for t in archived] == [task["id"]]
    assert archived[0]["archived"] == 1


async def test_patch_task_unarchive_restores_to_main_list(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    await api.patch(f"/api/tasks/{task['id']}", json={"archived": True})
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"archived": False})
    assert resp.status_code == 200
    assert resp.json()["archived"] == 0
    assert [t["id"] for t in (await api.get("/api/tasks")).json()["tasks"]] == [task["id"]]
    assert (await api.get("/api/tasks", params={"archived": 1})).json()["tasks"] == []


async def test_list_tasks_archived_param_rejects_invalid_value(api) -> None:
    assert (await api.get("/api/tasks", params={"archived": 2})).status_code == 422


async def test_projects_empty_by_default(api) -> None:
    resp = await api.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == {"projects": []}


async def test_create_and_list_projects(api) -> None:
    resp = await api.post("/api/projects", json={"name": "  调研  "})
    assert resp.status_code == 200
    project = resp.json()
    assert project["name"] == "调研"  # 已去首尾空白
    assert project["id"]
    assert project["created_at"]
    listed = (await api.get("/api/projects")).json()["projects"]
    assert [p["id"] for p in listed] == [project["id"]]


async def test_projects_list_orders_newest_first(api) -> None:
    first = (await api.post("/api/projects", json={"name": "最早"})).json()
    second = (await api.post("/api/projects", json={"name": "最新"})).json()
    ids = [p["id"] for p in (await api.get("/api/projects")).json()["projects"]]
    assert ids == [second["id"], first["id"]]


async def test_create_project_blank_name_400(api) -> None:
    assert (await api.post("/api/projects", json={"name": ""})).status_code == 400
    assert (await api.post("/api/projects", json={"name": "   "})).status_code == 400


async def test_patch_task_assign_project(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    project = (await api.post("/api/projects", json={"name": "调研"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"project_id": project["id"]})
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project["id"]
    # 列表里同样体现归组
    assert (await api.get("/api/tasks")).json()["tasks"][0]["project_id"] == project["id"]


async def test_patch_task_unknown_project_400(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"project_id": "no-such-project"})
    assert resp.status_code == 400  # 400 而非 404：避免与任务不存在歧义


async def test_patch_task_null_project_id_moves_out(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    project = (await api.post("/api/projects", json={"name": "调研"})).json()
    await api.patch(f"/api/tasks/{task['id']}", json={"project_id": project["id"]})
    # 显式 null = 移出项目，是合法操作，不算“全无有效字段”的 422
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"project_id": None})
    assert resp.status_code == 200
    assert resp.json()["project_id"] is None
    assert (await api.get("/api/tasks")).json()["tasks"][0]["project_id"] is None


async def test_patch_task_flag_regression_with_project_field(api) -> None:
    # project_id 字段加入后，原有布尔 flag 通道不受影响
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    resp = await api.patch(f"/api/tasks/{task['id']}", json={"pinned": True})
    assert resp.status_code == 200
    assert resp.json()["pinned"] == 1
    assert resp.json()["project_id"] is None


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
    assert events[0]["type"] == "user_stored"  # 落库回执是流内首事件
    assert events[1]["type"] == "delta"
    assert events[-1] == {"type": "done", "reply": "pong"}
    rows = (await api.get(f"/api/tasks/{task['id']}/messages")).json()["messages"]
    assert [r["kind"] for r in rows] == ["user", "assistant"]
    assert events[0]["id"] == rows[0]["id"]
    assert events[0]["created_at"] == rows[0]["created_at"]


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


async def test_stop_endpoint_idempotent(api) -> None:
    # 无活动流时停止是幂等 no-op：用户可能在流刚结束的那刻才点下"停止"。
    resp = await api.post("/api/tasks", json={"agent_type": "react"})
    task_id = resp.json()["id"]
    stop = await api.post(f"/api/tasks/{task_id}/stop")
    assert stop.status_code == 200
    assert stop.json() == {"ok": True}

    missing = await api.post("/api/tasks/not-a-task/stop")
    assert missing.status_code == 404


def test_sse_ping_encodes_as_comment() -> None:
    # ping 只是探活不是聊天事件：编码成 SSE comment 帧，前端 parseSseBlock 天然忽略。
    assert _sse({"type": "ping"}) == ": keep-alive\n\n"
    assert _sse({"type": "delta", "text": "你"}) == 'data: {"type": "delta", "text": "你"}\n\n'


async def test_delete_turn_removes_tail_turn_via_api(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    async with api.stream("POST", f"/api/tasks/{task['id']}/messages", json={"content": "问"}) as resp:
        await resp.aread()
    rows = (await api.get(f"/api/tasks/{task['id']}/messages")).json()["messages"]
    user_row = next(r for r in rows if r["kind"] == "user")

    resp = await api.delete(f"/api/tasks/{task['id']}/messages/{user_row['id']}")
    assert resp.status_code == 204
    assert (await api.get(f"/api/tasks/{task['id']}/messages")).json()["messages"] == []


async def test_delete_turn_rejects_assistant_row_and_missing_task(api) -> None:
    task = (await api.post("/api/tasks", json={"agent_type": "react"})).json()
    async with api.stream("POST", f"/api/tasks/{task['id']}/messages", json={"content": "问"}) as resp:
        await resp.aread()
    rows = (await api.get(f"/api/tasks/{task['id']}/messages")).json()["messages"]
    assistant_row = next(r for r in rows if r["kind"] == "assistant")
    # assistant 行不是轮次锚点 → 404；任务不存在同样 404
    assert (await api.delete(f"/api/tasks/{task['id']}/messages/{assistant_row['id']}")).status_code == 404
    assert (await api.delete(f"/api/tasks/{task['id']}/messages/999999")).status_code == 404
    assert (await api.delete("/api/tasks/nope/messages/1")).status_code == 404


async def test_delete_turn_evicts_cached_agent_so_next_reply_replays_trimmed_history(
    tmp_path, scripted_client
) -> None:
    # 删除轮次后立即发新消息：缓存 agent 的 transcript 仍记着吃进被删内容（服务端状态依赖
    # DB 重放恢复）。端点删除后必须 evict，否则被删内容会复活进模型上下文。
    seen: list[list[dict]] = []
    client = scripted_client(tool_completions=[])
    client.model_name = "mock-model"

    async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        seen.append(list(messages))
        completion = ToolCompletion(text="记录在案", requested_tools=[], model_id="mock-model")
        if on_text_delta is not None:
            for ch in completion.text:
                await on_text_delta(ch)
        return completion

    client.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
    runtime = ChatRuntime(
        ChatStore(tmp_path / "chat.db"),
        model_client=client,
        skill_service_url="http://127.0.0.1:1",
        trace_dir=tmp_path / "traces",
    )
    local = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    )
    task = (await local.post("/api/tasks", json={"agent_type": "react"})).json()
    async with local.stream(
        "POST", f"/api/tasks/{task['id']}/messages", json={"content": "暗号是foo"}
    ) as resp:
        await resp.aread()
    rows = (await local.get(f"/api/tasks/{task['id']}/messages")).json()["messages"]
    user_row = next(r for r in rows if r["kind"] == "user")
    assert (await local.delete(f"/api/tasks/{task['id']}/messages/{user_row['id']}")).status_code == 204

    async with local.stream(
        "POST", f"/api/tasks/{task['id']}/messages", json={"content": "暗号是什么"}
    ) as resp:
        await resp.aread()

    transcript = json.dumps(seen[-1], ensure_ascii=False)
    assert "暗号是foo" not in transcript  # 被删轮次不复活
    assert "记录在案" not in transcript
    assert "暗号是什么" in transcript
