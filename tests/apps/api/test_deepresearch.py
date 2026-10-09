"""DeepResearch 核心逻辑：解析弹性 + 单条 TODO 失败不传染 + 整体编排的测试。"""
import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.protocol import Completion
from db import ChatStore
from websearch.client import TavilyClient
from websearch.models import SearchResult

from deepresearch import (
    PlanningError,
    _live_runs,
    _parse_queries,
    _plan,
    _publish,
    _run_todo,
    _synthesize_report,
    run_research,
    start_live_run,
)


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    return ChatStore(tmp_path / "chat.db")


def _tavily_with_results(results: list[SearchResult]) -> TavilyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": "q", "results": [r.model_dump() for r in results]})

    return TavilyClient("tvly-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _tavily_erroring() -> TavilyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return TavilyClient("tvly-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


class TestParseQueries:
    def test_plain_json_array(self) -> None:
        assert _parse_queries('["q1", "q2", "q3"]') == ["q1", "q2", "q3"]

    def test_array_wrapped_in_prose(self) -> None:
        assert _parse_queries('好的：\n["q1", "q2", "q3"]\n') == ["q1", "q2", "q3"]

    def test_not_json_returns_empty(self) -> None:
        assert _parse_queries("不是 JSON") == []

    def test_caps_at_five(self) -> None:
        text = '["q0","q1","q2","q3","q4","q5","q6","q7"]'
        assert _parse_queries(text) == ["q0", "q1", "q2", "q3", "q4"]


class TestPlan:
    async def test_returns_queries_on_success(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text='["q1","q2","q3"]', model_id="mock-model")])
        assert await _plan(client, "topic") == ["q1", "q2", "q3"]

    async def test_raises_planning_error_on_too_few_queries(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text='["q1"]', model_id="mock-model")])
        with pytest.raises(PlanningError):
            await _plan(client, "topic")

    async def test_raises_planning_error_on_model_failure(self, scripted_client) -> None:
        client = scripted_client()

        async def raising(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
            raise RuntimeError("model down")

        client.acomplete = raising  # type: ignore[method-assign]
        with pytest.raises(PlanningError):
            await _plan(client, "topic")


class TestRunTodo:
    async def test_returns_completed_with_summary_and_sources(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="总结内容", model_id="mock-model")])
        search_client = _tavily_with_results([
            SearchResult(title="标题1", url="https://a.example", content="内容1", score=0.9),
        ])
        result = await _run_todo(client, search_client, "查询语句")
        assert result == {
            "status": "completed",
            "summary": "总结内容",
            "sources": [{"title": "标题1", "url": "https://a.example"}],
        }

    async def test_search_failure_degrades_to_failed_status(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="不应该用到", model_id="mock-model")])
        result = await _run_todo(client, _tavily_erroring(), "查询语句")
        assert result["status"] == "failed"
        assert result["sources"] == []

    async def test_empty_search_results_degrades_to_failed_status(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="不应该用到", model_id="mock-model")])
        result = await _run_todo(client, _tavily_with_results([]), "查询语句")
        assert result["status"] == "failed"


class TestSynthesizeReport:
    async def test_returns_report_text_on_success(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="# 报告正文", model_id="mock-model")])
        todos = [{"id": 0, "query": "q1", "status": "completed", "summary": "s1", "sources": []}]
        assert await _synthesize_report(client, "topic", todos) == "# 报告正文"

    async def test_raises_planning_error_when_no_completed_todos(self, scripted_client) -> None:
        client = scripted_client()
        todos = [{"id": 0, "query": "q1", "status": "failed", "summary": "err", "sources": []}]
        with pytest.raises(PlanningError):
            await _synthesize_report(client, "topic", todos)

    async def test_invokes_on_chunk_for_each_delta_and_reconstructs_full_text(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="abc", model_id="mock-model")])
        todos = [{"id": 0, "query": "q1", "status": "completed", "summary": "s1", "sources": []}]
        chunks: list[str] = []

        async def on_chunk(delta: str) -> None:
            chunks.append(delta)

        report = await _synthesize_report(client, "topic", todos, on_chunk=on_chunk)

        assert report == "abc"
        assert "".join(chunks) == "abc"
        assert len(chunks) == 3  # scripted_client 的 fake_astream 逐字符 yield

    async def test_mid_stream_failure_raises_planning_error_with_exception_type(self, scripted_client) -> None:
        client = scripted_client()

        async def raising_astream(_messages: list[dict[str, Any]], **_kwargs: Any):
            yield "部分"
            raise RuntimeError("stream broke")

        client.astream = raising_astream  # type: ignore[method-assign]
        todos = [{"id": 0, "query": "q1", "status": "completed", "summary": "s1", "sources": []}]

        with pytest.raises(PlanningError, match="RuntimeError"):
            await _synthesize_report(client, "topic", todos)


class TestRunResearch:
    async def test_full_flow_persists_completed_run_with_report(self, store, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(text='["q1","q2","q3"]', model_id="mock-model"),  # 规划
            Completion(text="总结1", model_id="mock-model"),              # TODO 0 总结
            Completion(text="总结2", model_id="mock-model"),              # TODO 1 总结
            Completion(text="总结3", model_id="mock-model"),              # TODO 2 总结
            Completion(text="# 最终报告", model_id="mock-model"),         # 合成报告
        ])
        search_client = _tavily_with_results([
            SearchResult(title="标题", url="https://a.example", content="内容", score=0.9),
        ])
        run = store.create_deepresearch_run("研究主题")

        await run_research(store, run["id"], client, search_client, "研究主题")

        final = store.get_deepresearch_run(run["id"])
        assert final["status"] == "completed"
        assert final["report"] == "# 最终报告"
        assert len(final["todos"]) == 3
        assert all(t["status"] == "completed" for t in final["todos"])

    async def test_planning_failure_marks_run_failed(self, store, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="不是数组", model_id="mock-model")])
        run = store.create_deepresearch_run("研究主题")

        await run_research(store, run["id"], client, _tavily_erroring(), "研究主题")

        final = store.get_deepresearch_run(run["id"])
        assert final["status"] == "failed"
        assert final["error"]

    async def test_all_todos_failing_marks_run_failed(self, store, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text='["q1","q2","q3"]', model_id="mock-model")])
        run = store.create_deepresearch_run("研究主题")

        await run_research(store, run["id"], client, _tavily_erroring(), "研究主题")

        final = store.get_deepresearch_run(run["id"])
        assert final["status"] == "failed"
        assert all(t["status"] == "failed" for t in final["todos"])

    async def test_broadcasts_full_event_sequence_on_success(self, store, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(text='["q1","q2","q3"]', model_id="mock-model"),
            Completion(text="总结1", model_id="mock-model"),
            Completion(text="总结2", model_id="mock-model"),
            Completion(text="总结3", model_id="mock-model"),
            Completion(text="报告", model_id="mock-model"),
        ])
        search_client = _tavily_with_results([
            SearchResult(title="标题", url="https://a.example", content="内容", score=0.9),
        ])
        run = store.create_deepresearch_run("研究主题")
        start_live_run(run["id"])
        queue: asyncio.Queue = asyncio.Queue()
        _live_runs[run["id"]].subscribers.append(queue)

        await run_research(store, run["id"], client, search_client, "研究主题")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        # 前 3 条：规划完成后逐条初始化为 pending，严格按 id 顺序（这段是顺序执行，不是并发）
        pending_events = events[:3]
        assert [(e["type"], e["id"], e["status"]) for e in pending_events] == [
            ("todo_update", 0, "pending"), ("todo_update", 1, "pending"), ("todo_update", 2, "pending"),
        ]

        # 中间 6 条：3 条 TODO 各自的 running→completed，并发执行，顺序不保证，只断言集合
        concurrent_events = events[3:9]
        seen = {(e["id"], e["status"]) for e in concurrent_events}
        assert seen == {
            (0, "running"), (0, "completed"),
            (1, "running"), (1, "completed"),
            (2, "running"), (2, "completed"),
        }
        assert all(e["type"] == "todo_update" and "query" in e and "sources" in e for e in concurrent_events)

        # 之后：report_chunk×N，拼起来等于完整报告
        report_events = events[9:-1]
        assert all(e["type"] == "report_chunk" for e in report_events)
        assert "".join(e["delta"] for e in report_events) == "报告"

        # 最后一条：run_done
        assert events[-1] == {"type": "run_done", "status": "completed", "report": "报告", "error": None}

        # 收尾：_live_runs 条目已清理，不会内存泄漏
        assert run["id"] not in _live_runs

    async def test_broadcasts_run_done_failed_on_planning_failure(self, store, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="不是数组", model_id="mock-model")])
        run = store.create_deepresearch_run("研究主题")
        start_live_run(run["id"])
        queue: asyncio.Queue = asyncio.Queue()
        _live_runs[run["id"]].subscribers.append(queue)

        await run_research(store, run["id"], client, _tavily_erroring(), "研究主题")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert len(events) == 1
        assert events[0]["type"] == "run_done"
        assert events[0]["status"] == "failed"
        assert run["id"] not in _live_runs

    async def test_mid_stream_report_failure_discards_partial_text(self, store, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(text='["q1","q2","q3"]', model_id="mock-model"),
            Completion(text="总结1", model_id="mock-model"),
            Completion(text="总结2", model_id="mock-model"),
            Completion(text="总结3", model_id="mock-model"),
        ])

        async def raising_astream(_messages: list[dict[str, Any]], **_kwargs: Any):
            yield "部分报告"
            raise RuntimeError("stream broke")

        client.astream = raising_astream  # type: ignore[method-assign]
        search_client = _tavily_with_results([
            SearchResult(title="标题", url="https://a.example", content="内容", score=0.9),
        ])
        run = store.create_deepresearch_run("研究主题")
        start_live_run(run["id"])
        queue: asyncio.Queue = asyncio.Queue()
        _live_runs[run["id"]].subscribers.append(queue)

        await run_research(store, run["id"], client, search_client, "研究主题")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events[-2] == {"type": "report_chunk", "delta": "部分报告"}
        assert events[-1]["type"] == "run_done"
        assert events[-1]["status"] == "failed"

        final = store.get_deepresearch_run(run["id"])
        assert final["report"] is None  # 半截文本不落库


class TestLiveRunBroadcaster:
    def test_publish_without_live_entry_is_noop(self) -> None:
        _publish("no-such-run", {"type": "todo_update"})  # 不应该抛异常

    async def test_publish_fans_out_to_all_subscribers(self) -> None:
        start_live_run("run-1")
        try:
            q1: asyncio.Queue = asyncio.Queue()
            q2: asyncio.Queue = asyncio.Queue()
            _live_runs["run-1"].subscribers.extend([q1, q2])

            _publish("run-1", {"type": "todo_update", "id": 0})

            assert q1.get_nowait() == {"type": "todo_update", "id": 0}
            assert q2.get_nowait() == {"type": "todo_update", "id": 0}
        finally:
            _live_runs.pop("run-1", None)
