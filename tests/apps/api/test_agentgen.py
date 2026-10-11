"""一句话生成 Agent：解析弹性、技能过滤、失败如实报错，以及端点/任务绑定的守护测试。"""
import asyncio
import json
from typing import Any

import httpx
import pytest
from agentgen import AgentGenerationError, _parse_spec, generate_agent_spec
from core.protocol import Completion
from db import ChatStore
from main import create_app
from runtime import ChatRuntime

_SPEC = {"name": "周报助手", "description": "整理周报", "system_prompt": "你是周报助手。", "skills": ["a", "ghost"]}


class TestParseSpec:
    def test_plain_json(self) -> None:
        spec = _parse_spec(json.dumps(_SPEC, ensure_ascii=False), {"a"})
        assert (spec.name, spec.system_prompt) == ("周报助手", "你是周报助手。")

    def test_wrapped_in_prose_and_unknown_skills_dropped(self) -> None:
        text = "好的：\n```json\n" + json.dumps(_SPEC, ensure_ascii=False) + "\n```"
        assert _parse_spec(text, {"a"}).skills == ["a"]

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(AgentGenerationError):
            _parse_spec('{"name": "x"}', set())

    def test_not_json_raises(self) -> None:
        with pytest.raises(AgentGenerationError):
            _parse_spec("抱歉我做不到", set())


def test_model_error_is_reported_not_swallowed(scripted_client) -> None:
    client = scripted_client()

    async def raising(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
        raise RuntimeError("model down")

    client.acomplete = raising  # type: ignore[method-assign]
    with pytest.raises(AgentGenerationError, match="model down"):
        asyncio.run(generate_agent_spec(client, "写周报", []))


@pytest.fixture
def api(tmp_path, scripted_client):
    client = scripted_client(completions=[Completion(text=json.dumps(_SPEC, ensure_ascii=False), model_id="mock-model")])
    runtime = ChatRuntime(ChatStore(tmp_path / "chat.db"), model_client=client, trace_dir=tmp_path / "traces")
    app = create_app(runtime, eval_cases_path=tmp_path / "eval_cases.json")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), runtime


async def test_generate_list_bind_delete(api) -> None:
    http, runtime = api
    resp = await http.post("/api/agents/generate", json={"prompt": "帮我写周报"})
    assert resp.status_code == 201
    agent = resp.json()
    assert agent["name"] == "周报助手" and agent["source_prompt"] == "帮我写周报"
    assert agent["skills"] == []  # "a"/"ghost" 都不在真实技能清单里
    assert (await http.get("/api/agents")).json()["agents"][0]["id"] == agent["id"]

    task = (await http.post("/api/tasks", json={"agent_id": agent["id"]})).json()
    assert task["agent_id"] == agent["id"]
    assert (await http.get(f"/api/tasks/{task['id']}")).json()["agent_name"] == "周报助手"
    suffix = await runtime._suffix_for(task)
    assert suffix is not None and suffix.startswith("你是周报助手。")

    assert (await http.delete(f"/api/agents/{agent['id']}")).status_code == 204
    # Agent 被删后任务退回默认 Agent，不报错
    assert (await http.get(f"/api/tasks/{task['id']}")).json()["agent_name"] is None
    assert (await http.get("/api/tasks/nope")).status_code == 404
    await runtime._ensure_skills()
    assert await runtime._suffix_for(task) == runtime._skills_suffix


async def test_empty_prompt_and_unknown_agent_rejected(api) -> None:
    http, _ = api
    assert (await http.post("/api/agents/generate", json={"prompt": "  "})).status_code == 422
    assert (await http.post("/api/tasks", json={"agent_id": "nope"})).status_code == 404
    assert (await http.delete("/api/agents/nope")).status_code == 404


async def test_generation_failure_is_502(tmp_path, scripted_client) -> None:
    client = scripted_client(completions=[Completion(text="不是 JSON", model_id="mock-model")])
    runtime = ChatRuntime(ChatStore(tmp_path / "chat.db"), model_client=client, trace_dir=tmp_path / "t")
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test")
    resp = await http.post("/api/agents/generate", json={"prompt": "x"})
    assert resp.status_code == 502
    assert (await http.get("/api/agents")).json()["agents"] == []
