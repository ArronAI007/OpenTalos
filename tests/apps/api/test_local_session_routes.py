import sys
from pathlib import Path

import httpx
import pytest

from fastapi import FastAPI

_API_DIR = Path(__file__).resolve().parents[3] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from agent_platform.sessions import LocalSessionService  # noqa: E402
from local_session_routes import create_local_session_router  # noqa: E402


@pytest.fixture
async def local_session_api(tmp_path: Path):
    home = tmp_path / "home"
    session_id = "11111111-1111-1111-1111-111111111111"
    index = home / ".codex" / "session_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_text(
        '{"id":"%s","thread_name":"本地 Codex","updated_at":"2026-11-17T00:00:00Z"}\n'
        % session_id,
        encoding="utf-8",
    )
    rollout = (
        home
        / ".codex"
        / "sessions"
        / "2026"
        / "11"
        / "17"
        / f"rollout-{session_id}.jsonl"
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        "\n".join(
            [
                '{"type":"session_meta","payload":{"id":"%s","cwd":"/work"}}'
                % session_id,
                '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"你好"}]}}',
                '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"你好。"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(create_local_session_router(LocalSessionService(home)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_local_session_routes(local_session_api) -> None:
    listing = await local_session_api.get("/api/local-sessions")
    assert listing.status_code == 200
    assert listing.json()["sessions"][0]["title"] == "本地 Codex"

    detail = await local_session_api.get(
        "/api/local-sessions/codex/11111111-1111-1111-1111-111111111111"
    )
    assert detail.status_code == 200
    assert [message["content"] for message in detail.json()["messages"]] == [
        "你好",
        "你好。",
    ]

    missing = await local_session_api.get(
        "/api/local-sessions/unknown/11111111-1111-1111-1111-111111111111"
    )
    assert missing.status_code == 404
