import httpx
import pytest

import app as console_app
from core.model import ModelClient


@pytest.fixture
def mock_model_client(monkeypatch):
    client = ModelClient(provider="mock")
    monkeypatch.setattr(console_app, "_get_model_client", lambda: (client, None))
    return client


def _patch_skill_client(monkeypatch, handler):
    real_client_cls = console_app.SkillClient
    monkeypatch.setattr(
        console_app,
        "SkillClient",
        lambda url: real_client_cls(url, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
    )


def _skills_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/skills":
        return httpx.Response(200, json={"skills": [{"name": "date", "description": "计算相对于今天的日期。"}]})
    return httpx.Response(404, json={"detail": "Unknown skill."})


async def test_make_agent_with_skills_registers_skill_tools_and_prompt_section(monkeypatch, mock_model_client):
    _patch_skill_client(monkeypatch, _skills_handler)

    agent, error = await console_app._make_agent("toolcall", use_calculator=False, use_skills=True)

    assert error is None
    tool_names = {tool.name for tool in agent.tool_registry.list_tools()}
    assert {"read_skill", "run_skill_script"} <= tool_names
    assert "<available_skills>" in agent.system_prompt
    assert "<name>date</name>" in agent.system_prompt


async def test_make_agent_with_an_unreachable_skill_service_returns_an_error(monkeypatch, mock_model_client):
    def refusing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_skill_client(monkeypatch, refusing_handler)

    agent, error = await console_app._make_agent("toolcall", use_calculator=False, use_skills=True)

    assert agent is None
    assert "skill service" in error


async def test_make_agent_without_skills_stays_off_the_network(mock_model_client):
    agent, error = await console_app._make_agent("toolcall", use_calculator=False, use_skills=False)

    assert error is None
    assert agent.tool_registry is None
