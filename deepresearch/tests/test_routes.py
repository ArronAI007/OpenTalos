import asyncio
import json

import httpx
import pytest
from core.protocol import Completion
from websearch.client import TavilyClient

import main as main_module
from main import app
from store import DeepResearchStore


def _tavily_with_results() -> TavilyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"query": "q", "results": [{"title": "t", "url": "https://a.example", "content": "c", "score": 0.9}]},
        )

    return TavilyClient("tvly-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "store", DeepResearchStore(tmp_path / "deepresearch.db"))
    yield


def _stub_clients(monkeypatch, scripted_client, *, with_tavily: bool = True) -> None:
    client = scripted_client(completions=[
        Completion(text='["q1","q2","q3"]', model_id="mock-model"),
        Completion(text="总结1", model_id="mock-model"),
        Completion(text="总结2", model_id="mock-model"),
        Completion(text="总结3", model_id="mock-model"),
        Completion(text="# 报告", model_id="mock-model"),
    ])
    monkeypatch.setattr(main_module, "_get_model_client", lambda: client)
    search_client = _tavily_with_results() if with_tavily else None
    monkeypatch.setattr(main_module, "_get_search_client", lambda: search_client)


@pytest.fixture
def api():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health(api) -> None:
    resp = await api.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_run_without_tavily_key_returns_503(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client, with_tavily=False)
    resp = await api.post("/runs", json={"topic": "topic"})
    assert resp.status_code == 503


async def test_create_run_rejects_blank_topic(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    resp = await api.post("/runs", json={"topic": "   "})
    assert resp.status_code == 400


async def test_run_completes_and_is_listed(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    created = await api.post("/runs", json={"topic": "研究主题"})
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["status"] == "running"

    fetched = created
    for _ in range(50):
        fetched = await api.get(f"/runs/{run_id}")
        if fetched.json()["status"] != "running":
            break
        await asyncio.sleep(0.05)

    assert fetched.json()["status"] == "completed"
    assert fetched.json()["report"] == "# 报告"

    listed = await api.get("/runs")
    assert [r["id"] for r in listed.json()["runs"]] == [run_id]


async def test_get_missing_run_returns_404(api) -> None:
    resp = await api.get("/runs/no-such-id")
    assert resp.status_code == 404


async def test_stream_full_event_sequence(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    created = await api.post("/runs", json={"topic": "研究主题"})
    run_id = created.json()["id"]

    async with api.stream("GET", f"/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = (await resp.aread()).decode()

    frames = [block for block in body.split("\n\n") if block.strip()]
    events = [json.loads(frame.strip().removeprefix("data: ")) for frame in frames]

    # 后台任务和这次 stream 连接之间存在真实竞态（事件循环调度顺序不保证）：如果后台任务在
    # stream 连上之前就已经跑完，只会收到一帧终态 snapshot，不会有 run_done——这是
    # stream_run_events 的既有设计（见 research.py 的 docstring），不是 bug。完整的"先订阅、
    # 后续事件逐条到达"路径已经在 test_research.py::TestRunResearch 里用直接调用
    # run_research（不经过 HTTP，没有这个竞态）确定性地覆盖过，这里只需要确认两种结局都能
    # 正确反映"研究已成功完成"。
    assert events[0]["type"] == "snapshot"
    final = events[-1]
    if final["type"] == "run_done":
        assert final["status"] == "completed"
        assert final["report"] == "# 报告"
    else:
        assert final["type"] == "snapshot"
        assert final["run"]["status"] == "completed"
        assert final["run"]["report"] == "# 报告"


async def test_stream_on_terminal_run_closes_immediately(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    created = await api.post("/runs", json={"topic": "研究主题"})
    run_id = created.json()["id"]

    fetched = created
    for _ in range(50):
        fetched = await api.get(f"/runs/{run_id}")
        if fetched.json()["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert fetched.json()["status"] == "completed"

    async with api.stream("GET", f"/runs/{run_id}/stream") as resp:
        body = (await resp.aread()).decode()

    frames = [block for block in body.split("\n\n") if block.strip()]
    events = [json.loads(frame.strip().removeprefix("data: ")) for frame in frames]
    assert len(events) == 1
    assert events[0]["type"] == "snapshot"
    assert events[0]["run"]["status"] == "completed"


async def test_stream_missing_run_yields_error_frame(api) -> None:
    async with api.stream("GET", "/runs/no-such-id/stream") as resp:
        body = (await resp.aread()).decode()
    frames = [block for block in body.split("\n\n") if block.strip()]
    events = [json.loads(frame.strip().removeprefix("data: ")) for frame in frames]
    assert events == [{"type": "error", "message": "run not found"}]


async def test_delete_missing_run_returns_404(api) -> None:
    resp = await api.delete("/runs/no-such-id")
    assert resp.status_code == 404


async def test_delete_running_run_returns_409(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    created = await api.post("/runs", json={"topic": "topic"})
    run_id = created.json()["id"]
    # 立即删除：POST /runs 同步把 status 设成 running，后台任务要到下一次事件循环调度才真正
    # 开始跑规划调用——紧跟着删，不需要额外手段就能稳定撞见 running 状态。
    resp = await api.delete(f"/runs/{run_id}")
    assert resp.status_code == 409


async def test_delete_completed_run_returns_204(api, monkeypatch, scripted_client) -> None:
    _stub_clients(monkeypatch, scripted_client)
    created = await api.post("/runs", json={"topic": "topic"})
    run_id = created.json()["id"]

    fetched = created
    for _ in range(50):
        fetched = await api.get(f"/runs/{run_id}")
        if fetched.json()["status"] != "running":
            break
        await asyncio.sleep(0.05)

    resp = await api.delete(f"/runs/{run_id}")
    assert resp.status_code == 204
    assert (await api.get("/runs")).json()["runs"] == []
