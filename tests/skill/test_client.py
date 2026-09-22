import json

import httpx
import pytest

from skill.client import SkillClient, SkillServiceError


def _build_client(handler) -> SkillClient:
    return SkillClient("http://skill.test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_list_skills_returns_summaries():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/skills"
        return httpx.Response(200, json={"skills": [{"name": "date", "description": "dates"}]})

    skills = await _build_client(handler).list_skills()

    assert [(skill.name, skill.description) for skill in skills] == [("date", "dates")]


async def test_read_skill_returns_the_skill_md_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/skills/date"
        return httpx.Response(200, json={"name": "date", "content": "# date\n\nusage..."})

    content = await _build_client(handler).read_skill("date")

    assert content == "# date\n\nusage..."


async def test_read_skill_raises_with_the_service_detail_for_unknown_skills():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": 'Unknown skill "nope".'})

    with pytest.raises(SkillServiceError, match='Unknown skill "nope"'):
        await _build_client(handler).read_skill("nope")


async def test_run_script_posts_the_request_body_and_returns_the_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/skills/date/run-script"
        body = json.loads(request.content)
        assert body == {
            "script_relative_path": "scripts/main.py",
            "args": ["7"],
            "input_text": None,
            "timeout_ms": 10_000,
        }
        return httpx.Response(200, json={"stdout": "2026-09-29\n", "stderr": "", "exit_code": 0, "timed_out": False})

    result = await _build_client(handler).run_script("date", "scripts/main.py", args=["7"])

    assert result.exit_code == 0
    assert result.stdout == "2026-09-29\n"


async def test_run_script_rejects_oversized_input_before_hitting_the_network():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be reached
        raise AssertionError("request should not have been sent")

    with pytest.raises(SkillServiceError, match="too large"):
        await _build_client(handler).run_script("csv-to-json", "convert.py", input_text="a" * 65_537)


async def test_an_unreachable_service_raises_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SkillServiceError, match="unreachable"):
        await _build_client(handler).list_skills()
