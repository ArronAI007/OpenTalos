import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from core.protocol import ToolCompletion, ToolInvocation
from db import ChatStore
from runtime import ChatRuntime


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    return ChatStore(tmp_path / "chat.db")


def _runtime(store: ChatStore, client, tmp_path: Path, **kwargs: Any) -> ChatRuntime:
    return ChatRuntime(
        store,
        model_client=client,
        skill_service_url="http://127.0.0.1:1",  # 不可达端口 → 技能自动降级
        trace_dir=tmp_path / "traces",
        **kwargs,
    )


async def _collect(runtime: ChatRuntime, task_id: str, content: str) -> list[dict[str, Any]]:
    return [event async for event in runtime.stream_reply(task_id, content)]


def test_stream_plain_reply_deltas_and_persists(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好，世界", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "hi"))

    assert [e["type"] for e in events][-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "你好，世界"
    rows = store.list_messages(task["id"])
    assert [(r["kind"], r["content"]) for r in rows] == [("user", "hi"), ("assistant", "你好，世界")]
    assert store.get_task(task["id"])["title"] == "hi"


def test_disconnect_mid_stream_persists_partial(store, scripted_client, tmp_path) -> None:
    # 前端"停止"会 abort fetch；SSE 断开时消费循环被中断，正常完成路径的落库不可达。
    # 期望：已流出的部分内容兜底落库，刷新后仍可见。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好，世界！", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    async def consume_one_delta_then_close() -> str:
        gen = runtime.stream_reply(task["id"], "hi")
        first = await gen.__anext__()
        assert first["type"] == "delta"
        partial = first["text"]
        await gen.aclose()  # 模拟客户端中途断开（关闭 SSE）
        return partial

    partial = asyncio.run(consume_one_delta_then_close())

    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant", "stopped"]
    assert rows[1]["content"] == partial  # 恰好是用户实际看到的部分
    assert partial and "你好，世界！".startswith(partial)
    assert rows[2]["content"] == ""  # 停止标记本身无内容，渲染文案在前端


def test_disconnect_before_any_delta_persists_stopped_marker(store, scripted_client, tmp_path) -> None:
    # 立即停止（一个 delta 都还没发出就断开）：没有内容可落，但"已停止"标记必须落库，
    # 否则刷新后这次提问像从未发生过。
    client = scripted_client(tool_completions=[])

    async def slow_silent_astream(messages, tools, on_text_delta=None, **kwargs):
        await asyncio.sleep(3600)  # 永不产出；断连后由 stream_reply 的 producer.cancel() 收敛
        return ToolCompletion(text="", requested_tools=[], model_id="mock-model")  # pragma: no cover

    client.astream_with_tools = slow_silent_astream  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    async def close_before_first_event() -> None:
        gen = runtime.stream_reply(task["id"], "hi")
        reader = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)  # 让消费循环进入 queue.get() 等待（producer 被 sleep 阻塞）
        reader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader
        await gen.aclose()

    asyncio.run(close_before_first_event())

    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "stopped"]


def test_request_stop_persists_partial_and_stopped_row(store, scripted_client, tmp_path) -> None:
    # 用户点"停止"按钮（区别于断连）：前端先调 POST /stop 置位停止信号，再 abort 读取。
    # 服务端消费循环每轮首查信号 → 立即停流，走与断连相同的兜底：partial + stopped 标记落库。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好，世界！", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    async def consume_until_stop() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in runtime.stream_reply(task["id"], "hi"):
            events.append(event)
            if event["type"] == "delta":
                runtime.request_stop(task["id"])  # 见到首个增量即停止
        return events

    events = asyncio.run(consume_until_stop())

    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas
    assert not any(e["type"] == "done" for e in events)  # 提前终止，无 done
    partial = "".join(e["text"] for e in deltas)
    assert len(partial) < len("你好，世界！")  # 确实被截断而非跑完
    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant", "stopped"]
    assert rows[1]["content"] == partial


def test_idle_stream_emits_keepalive_ping(store, scripted_client, tmp_path) -> None:
    # 模型长时间无产出时，消费循环周期性发 ping：真实 HTTP 层只在写时才感知客户端
    # 断开，有数据可写才能让断连 ≤1s 内暴露、走落库兜底（ping 由编码层转成 SSE comment）。
    client = scripted_client(tool_completions=[])

    async def slow_silent_astream(messages, tools, on_text_delta=None, **kwargs):
        await asyncio.sleep(3600)  # 永不产出；aclose 时由 stream_reply 的 producer.cancel() 收敛
        return ToolCompletion(text="", requested_tools=[], model_id="mock-model")  # pragma: no cover

    client.astream_with_tools = slow_silent_astream  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    async def first_event() -> dict[str, Any]:
        gen = runtime.stream_reply(task["id"], "hi")
        try:
            return await asyncio.wait_for(gen.__anext__(), timeout=5)
        finally:
            await gen.aclose()

    first = asyncio.run(first_event())
    assert first["type"] == "ping"


def test_stream_tool_call_events_and_tool_row(store, scripted_client, echo_tool_registry, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(
            text="",
            requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text":"ping"}')],
            model_id="mock-model",
        ),
        ToolCompletion(text="回声是 ping", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path, tool_registry_factory=lambda: echo_tool_registry)
    task = store.create_task("toolcall")

    events = asyncio.run(_collect(runtime, task["id"], "call the echo tool"))

    tool_call = next(e for e in events if e["type"] == "tool_call")
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_call["name"] == "echo" and tool_call["arguments"] == {"text": "ping"}
    assert tool_result["name"] == "echo" and tool_result["ok"] is True
    assert "echoed: ping" in tool_result["result"]
    tool_rows = [r for r in store.list_messages(task["id"]) if r["kind"] == "tool"]
    assert json.loads(tool_rows[0]["content"])["name"] == "echo"


def test_rebuild_replays_user_assistant_history(store, scripted_client, tmp_path) -> None:
    seen_messages: list[list[dict]] = []

    async def run_twice() -> None:
        first_client = scripted_client(tool_completions=[
            ToolCompletion(text="记住了，foo", requested_tools=[], model_id="mock-model"),
        ])
        runtime_a = _runtime(store, first_client, tmp_path)
        task = store.create_task("react")
        await _collect(runtime_a, task["id"], "暗号是foo")

        replaying = scripted_client(tool_completions=[])

        async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
            seen_messages.append(list(messages))
            completion = ToolCompletion(text="暗号确认：foo", requested_tools=[], model_id="mock-model")
            if on_text_delta is not None:
                for ch in completion.text:
                    await on_text_delta(ch)
            return completion

        replaying.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
        runtime_b = _runtime(store, replaying, tmp_path)  # 新 runtime = 模拟重启，从 DB 重建 agent
        await _collect(runtime_b, task["id"], "暗号是什么？")

    asyncio.run(run_twice())
    transcript_text = json.dumps(seen_messages[-1], ensure_ascii=False)
    assert "暗号是foo" in transcript_text and "记住了，foo" in transcript_text


def test_missing_task_yields_error_event(store, scripted_client, tmp_path) -> None:
    runtime = _runtime(store, scripted_client(tool_completions=[]), tmp_path)
    events = asyncio.run(_collect(runtime, "no-such-task", "hi"))
    assert events == [{"type": "error", "message": "task not found: no-such-task"}]


def test_current_user_message_not_duplicated_in_transcript(store, scripted_client, tmp_path) -> None:
    seen: list[list[dict]] = []
    client = scripted_client(tool_completions=[])

    async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        seen.append(list(messages))
        completion = ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")
        if on_text_delta is not None:
            for ch in completion.text:
                await on_text_delta(ch)
        return completion

    client.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    asyncio.run(_collect(runtime, task["id"], "只应出现一次"))

    user_msgs = [m for m in seen[-1] if m.get("role") == "user" and "只应出现一次" in str(m.get("content", ""))]
    assert len(user_msgs) == 1


def test_tool_schemas_reach_model_via_wrapper(store, scripted_client, echo_tool_registry, tmp_path) -> None:
    seen_tools: list[list[dict]] = []
    client = scripted_client(tool_completions=[])

    async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        seen_tools.append(list(tools))
        completion = ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")
        if on_text_delta is not None:
            for ch in completion.text:
                await on_text_delta(ch)
        return completion

    client.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path, tool_registry_factory=lambda: echo_tool_registry)
    task = store.create_task("toolcall")

    asyncio.run(_collect(runtime, task["id"], "show me your tools"))

    tool_names = [fn["function"]["name"] for tools in seen_tools for fn in tools]
    assert "echo" in tool_names


def test_agent_error_yields_error_event_and_no_assistant_row(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])

    async def exploding_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        raise RuntimeError("boom")

    client.astream_with_tools = exploding_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "trigger the failure"))

    assert any(e["type"] == "error" and "boom" in e["message"] for e in events)
    kinds = [r["kind"] for r in store.list_messages(task["id"])]
    assert "user" in kinds and "assistant" not in kinds


def test_concurrent_tasks_do_not_cross_streams(store, scripted_client, echo_tool_registry, tmp_path) -> None:
    client = scripted_client(tool_completions=[])

    async def tool_echo_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        user_content = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if not any(m.get("tool_calls") for m in messages):
            return ToolCompletion(
                text="",
                requested_tools=[ToolInvocation(
                    call_id="c1", tool_name="echo",
                    arguments_json=json.dumps({"text": user_content}),
                )],
                model_id="mock-model",
            )
        text = f"done-{user_content}"
        if on_text_delta is not None:
            for ch in text:
                await on_text_delta(ch)
        return ToolCompletion(text=text, requested_tools=[], model_id="mock-model")

    client.astream_with_tools = tool_echo_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path, tool_registry_factory=lambda: echo_tool_registry)
    task_a = store.create_task("toolcall")
    task_b = store.create_task("toolcall")

    async def collect(task_id: str, content: str) -> tuple[str, list[dict[str, Any]]]:
        return task_id, await _collect(runtime, task_id, content)

    async def run_both() -> list[tuple[str, list[dict[str, Any]]]]:
        return await asyncio.gather(
            collect(task_a["id"], "AAA"),
            collect(task_b["id"], "BBB"),
        )

    results = asyncio.run(run_both())

    for task_id, events in results:
        payload = json.dumps(events, ensure_ascii=False)
        if task_id == task_a["id"]:
            assert "AAA" in payload and "BBB" not in payload
        else:
            assert "BBB" in payload and "AAA" not in payload
