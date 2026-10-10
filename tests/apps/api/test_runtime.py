import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.protocol import Completion, ToolCompletion, ToolInvocation
from core.model import ModelClient
from db import ChatStore
from runtime import ChatRuntime
from tool.outcome import FailureCode, ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter


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


async def _collect_kw(runtime: ChatRuntime, task_id: str, content: str, **kwargs: Any) -> list[dict[str, Any]]:
    return [event async for event in runtime.stream_reply(task_id, content, **kwargs)]


async def _await_run_done(runtime: ChatRuntime, task_id: str) -> None:
    run = runtime._runs[task_id]
    for _ in range(500):
        if run.done:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish in time")


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


def test_user_stored_receipt_reports_persisted_row_identity(store, scripted_client, tmp_path) -> None:
    # user 行落库后回送 row id 与写入时间：前端据此把 live-N 泡换成 row-N 身份（删除轮次要 id），
    # 时间戳也校准为服务端时钟——两个进程谁的时钟准，以写库者为准。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="好的", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "登记我"))

    assert events[0]["type"] == "user_stored"  # 必为流内首事件（producer 启动前发出）
    user_rows = [r for r in store.list_messages(task["id"]) if r["kind"] == "user"]
    assert events[0]["id"] == user_rows[0]["id"]
    assert events[0]["created_at"] == user_rows[0]["created_at"]


def test_disconnect_mid_stream_keeps_the_turn_running(store, scripted_client, tmp_path) -> None:
    # 语义 A：断连只停止跟随，不再中止；运行照常跑完并落完整回复（不再落 partial+stopped）。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好，世界！", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")  # 跳过首条消息才有的标题事件，不干扰事件序列断言

    async def consume_one_delta_then_close() -> None:
        gen = runtime.stream_reply(task["id"], "hi")
        receipt = await gen.__anext__()
        assert receipt["type"] == "user_stored"  # 落库回执是流内首事件
        first_delta = await gen.__anext__()
        assert first_delta["type"] == "delta"
        await gen.aclose()  # 客户端中途断开（关闭 SSE）：只脱离，不中止
        await _await_run_done(runtime, task["id"])

    asyncio.run(consume_one_delta_then_close())

    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant"]
    assert rows[1]["content"] == "你好，世界！"


def test_disconnect_before_any_delta_does_not_persist_a_stopped_marker(store, scripted_client, tmp_path) -> None:
    # 语义 A：断连不再落 stopped 标记；运行继续，产出后落完整回复。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="迟到的回复", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")

    async def close_before_first_delta() -> None:
        gen = runtime.stream_reply(task["id"], "hi")
        receipt = await gen.__anext__()
        assert receipt["type"] == "user_stored"
        await gen.aclose()
        await _await_run_done(runtime, task["id"])

    asyncio.run(close_before_first_delta())

    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant"]
    assert rows[1]["content"] == "迟到的回复"


def test_request_stop_persists_partial_and_stopped_row(store, scripted_client, tmp_path) -> None:
    # 用户显式"停止"仍是中止路径：runner 落 partial + stopped 标记，并发终结事件。
    client = scripted_client(tool_completions=[])

    async def slow_stream(messages, tools, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        for ch in "你好，世界！":
            if on_text_delta is not None:
                await on_text_delta(ch)
            await asyncio.sleep(0.02)
        return ToolCompletion(text="你好，世界！", requested_tools=[], model_id="mock-model")

    client.astream_with_tools = slow_stream  # type: ignore[method-assign]
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

    types = [e["type"] for e in events]
    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas
    assert "done" not in types  # 提前终止，无 done
    assert "stopped" in types  # 终结事件
    partial = "".join(e["text"] for e in deltas)
    assert len(partial) < len("你好，世界！")  # 确实被截断而非跑完
    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant", "stopped"]
    assert rows[1]["content"] == partial


def test_resume_stream_replays_events_after_the_last_seen_id(store, scripted_client, tmp_path) -> None:
    # 重连续传：从 after=last_id+1 补发错过的 SSE 事件（含 done）。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="完整回复", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")

    async def scenario() -> list[dict[str, Any]]:
        gen = runtime.stream_reply(task["id"], "hi")
        await gen.__anext__()  # user_stored（id 0）
        delta = await gen.__anext__()  # 第一个 delta
        last_id = delta["_id"]
        await gen.aclose()  # 断连：只脱离
        await _await_run_done(runtime, task["id"])
        # 运行已结束但在 TTL 窗口内：从 last_id+1 补发剩余事件
        return [event async for event in runtime.stream_reply(task["id"], None, after=last_id + 1)]

    resumed = asyncio.run(scenario())

    assert resumed
    assert all(e["_id"] > 0 for e in resumed)
    assert "done" in [e["type"] for e in resumed]


def test_finished_run_is_swept_after_the_ttl(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(text="好", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path, run_ttl_seconds=0)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")

    async def scenario() -> list[dict[str, Any]]:
        async for _ in runtime.stream_reply(task["id"], "hi"):
            pass
        # run_ttl_seconds=0：下一次访问即回收，续传拿不到任何事件。
        return [event async for event in runtime.stream_reply(task["id"], None, after=0)]

    assert asyncio.run(scenario()) == []


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
    store.update_task(task["id"], title="已有标题")  # 跳过首条消息才有的标题事件，不干扰事件序列断言

    async def first_two_events() -> list[dict[str, Any]]:
        gen = runtime.stream_reply(task["id"], "hi")
        try:
            receipt = await asyncio.wait_for(gen.__anext__(), timeout=5)
            ping = await asyncio.wait_for(gen.__anext__(), timeout=5)
            return [receipt, ping]
        finally:
            await gen.aclose()

    receipt, ping = asyncio.run(first_two_events())
    assert receipt["type"] == "user_stored"
    assert ping["type"] == "ping"


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


def test_tool_row_persists_call_id(store, scripted_client, echo_tool_registry, tmp_path) -> None:
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

    asyncio.run(_collect(runtime, task["id"], "call the echo tool"))

    tool_rows = [r for r in store.list_messages(task["id"]) if r["kind"] == "tool"]
    data = json.loads(tool_rows[0]["content"])
    assert data["call_id"] == "c1"
    assert data["name"] == "echo"


def test_rebuild_replays_tool_history(store, scripted_client, echo_tool_registry, tmp_path) -> None:
    seen_messages: list[list[dict]] = []

    async def run_twice() -> None:
        first_client = scripted_client(tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text":"ping"}')],
                model_id="mock-model",
            ),
            ToolCompletion(text="回声是 ping", requested_tools=[], model_id="mock-model"),
        ])
        runtime_a = _runtime(store, first_client, tmp_path, tool_registry_factory=lambda: echo_tool_registry)
        task = store.create_task("toolcall")
        await _collect(runtime_a, task["id"], "echo ping")

        replaying = scripted_client(tool_completions=[])

        async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
            seen_messages.append(list(messages))
            return ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")

        replaying.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
        runtime_b = _runtime(store, replaying, tmp_path, tool_registry_factory=lambda: echo_tool_registry)
        await _collect(runtime_b, task["id"], "再来一次")

    asyncio.run(run_twice())

    messages = seen_messages[-1]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "c1"
    assert "echoed: ping" in tool_msgs[0]["content"]
    assistant_calls = [m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")]
    assert assistant_calls
    assert assistant_calls[0]["tool_calls"][0]["id"] == "c1"
    assert assistant_calls[0]["tool_calls"][0]["function"]["name"] == "echo"


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


def test_reasoning_deltas_stream_as_events_before_content(store, scripted_client, tmp_path) -> None:
    # 推理模型（kimi-k3 等）的思维链增量以独立 reasoning 事件流出：先于正文 delta，
    # 让前端在等待期就有可见反馈；思维链只是 UI 反馈，不落库。
    client = scripted_client(tool_completions=[])

    async def fake_astream_with_tools(messages, tools, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        assert on_reasoning_delta is not None, "runtime 必须把 reasoning 回调接进 agent 调用"
        await on_reasoning_delta("在想")
        await on_text_delta("答")
        return ToolCompletion(text="答", requested_tools=[], model_id="mock")

    client.astream_with_tools = fake_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "想想"))

    types = [e["type"] for e in events]
    assert "reasoning" in types
    assert types.index("reasoning") < types.index("delta")
    assert "".join(e["text"] for e in events if e["type"] == "reasoning") == "在想"
    rows = store.list_messages(task["id"])
    assert [r["kind"] for r in rows] == ["user", "assistant"]


def test_followup_suggestions_emitted_after_done(store, scripted_client, tmp_path) -> None:
    # 回复正常完成后，流内追加一次跟进问题推荐（done 之后、流尾）；
    # 推荐走独立 acomplete 调用（completions 队列），不影响 agent 的 toolcall 流。
    client = scripted_client(
        completions=[Completion(text='["然后呢？","举个例子"]', model_id="mock-model")],
        tool_completions=[ToolCompletion(text="答复", requested_tools=[], model_id="mock-model")],
    )
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "hi"))

    assert [e["type"] for e in events][-2:] == ["done", "suggestions"]
    assert events[-1]["items"] == ["然后呢？", "举个例子"]


def test_followup_suggestions_bad_output_is_silent(store, scripted_client, tmp_path) -> None:
    # 推荐输出无法解析时静默省略事件，回复与落库不受影响（无 suggestions，done 仍是流尾）。
    client = scripted_client(
        completions=[Completion(text="这不是 JSON", model_id="mock-model")],
        tool_completions=[ToolCompletion(text="答复", requested_tools=[], model_id="mock-model")],
    )
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "hi"))

    assert [e["type"] for e in events][-1] == "done"
    rows = store.list_messages(task["id"])
    assert [(r["kind"], r["content"]) for r in rows] == [("user", "hi"), ("assistant", "答复")]


def test_followup_suggestions_absent_on_stop(store, scripted_client, tmp_path) -> None:
    # 用户停止路径不产生推荐：stopped 提前收尾，到不了 done 之后的推荐段。
    client = scripted_client(completions=[Completion(text='["不应出现"]', model_id="mock-model")])

    async def slow_stream(messages, tools, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        for ch in "你好，世界！":
            if on_text_delta is not None:
                await on_text_delta(ch)
            await asyncio.sleep(0.02)
        return ToolCompletion(text="你好，世界！", requested_tools=[], model_id="mock-model")

    client.astream_with_tools = slow_stream  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")  # 跳过首条消息才有的标题事件

    async def consume_then_stop() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in runtime.stream_reply(task["id"], "hi"):
            events.append(event)
            if event["type"] == "delta":
                runtime.request_stop(task["id"])
        return events

    events = asyncio.run(consume_then_stop())

    types = [e["type"] for e in events]
    assert "suggestions" not in types
    assert "done" not in types


def test_followup_suggestions_prefetch_starts_with_reply(store, scripted_client, tmp_path) -> None:
    # 并行预发的决定性证据：done 事件到达时推荐调用必须已在飞（串行时代 done 之后才发起）。
    # 两道 asyncio.Event 闸门替代时钟断言，杜绝时序抖动。
    suggest_started = asyncio.Event()
    suggest_gate = asyncio.Event()
    captured: list[list[dict[str, Any]]] = []

    client = scripted_client(
        tool_completions=[ToolCompletion(text="答复", requested_tools=[], model_id="mock-model")],
    )

    async def gated_acomplete(messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        captured.append(messages)
        suggest_started.set()
        await suggest_gate.wait()
        return Completion(text='["然后呢？"]', model_id="mock-model")

    client.acomplete = gated_acomplete  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    # 标题生成只在任务还没标题（首条消息）时才会并行发起、同样调用 acomplete——这个测试
    # 专门断言"推荐调用先于 done 发起"，给任务先设好标题以跳过标题生成，避免两路并行调用
    # 互相抢占同一个 gated_acomplete/completions 队列。
    store.update_task(task["id"], title="已有标题")

    async def consume() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in runtime.stream_reply(task["id"], "hi"):
            events.append(event)
            if event["type"] == "done":
                # 预发生效：推荐在回复流式期间就已发起；放行让它收尾
                assert suggest_started.is_set()
                suggest_gate.set()
        return events

    events = asyncio.run(consume())

    assert [e["type"] for e in events][-2:] == ["done", "suggestions"]
    assert events[-1]["items"] == ["然后呢？"]
    # 预发语义：推荐只看得到历史+本轮提问，看不到尚未生成的回复
    prompt = captured[0][-1]["content"]
    assert "hi" in prompt
    assert "答复" not in prompt


def test_compression_persists_summary_checkpoint(store, scripted_client, tmp_path) -> None:
    # 压缩成功后落一条 kind="summary" 快照行（summary + 保留近期），重启据此恢复、不重新压。
    # completions 队列两个：首个给 suggest（返回 []，静默），次个给 summarize_history（摘要文本）。
    client = scripted_client(
        completions=[
            Completion(text="[]", model_id="mock-model"),
            Completion(text="早期讨论摘要", model_id="mock-model"),
        ],
        tool_completions=[ToolCompletion(text="答复", requested_tools=[], model_id="mock-model")],
    )
    task = store.create_task("react")
    # 同上：先设标题跳过标题生成，避免它抢占这里专门留给 suggest/summarize 的两格 completions 队列。
    store.update_task(task["id"], title="已有标题")
    for i in range(11):  # 种入 11 回合，第 12 轮触发压缩（min_retain_turns=10）
        store.append_message(task["id"], "user", f"问题 {i}")
        store.append_message(task["id"], "assistant", f"回答 {i}")

    runtime = _runtime(store, client, tmp_path, compaction_token_limit=1)
    asyncio.run(_collect(runtime, task["id"], "第 12 个问题"))

    summary_rows = [r for r in store.list_messages(task["id"]) if r["kind"] == "summary"]
    assert len(summary_rows) == 1
    checkpoint = json.loads(summary_rows[0]["content"])
    assert checkpoint["messages"][0]["role"] == "summary"
    assert "早期讨论摘要" in checkpoint["messages"][0]["content"]
    # 快照含保留的近期回合（本轮 user/assistant 也在内）
    assert any(m["role"] == "user" and "第 12 个问题" in m["content"] for m in checkpoint["messages"])


def test_rebuild_restores_summary_checkpoint_and_skips_folded(store, scripted_client, tmp_path) -> None:
    seen_messages: list[list[dict]] = []

    task = store.create_task("react")
    # 早期被折叠消息（不在快照里）
    store.append_message(task["id"], "user", "早期问题 A")
    store.append_message(task["id"], "assistant", "早期回答 A")
    # summary 快照行：summary + 近期回合
    checkpoint = {
        "messages": [
            {"content": "存档摘要", "role": "summary", "metadata": {"compressed_at": "2026-09-24T00:00:00"}},
            {"content": "近期问题 B", "role": "user"},
            {"content": "近期回答 B", "role": "assistant"},
        ],
        "saved_at": "2026-09-24T00:00:00",
        "turns": 1,
    }
    store.append_message(task["id"], "summary", json.dumps(checkpoint, ensure_ascii=False))
    # summary 之后的新消息
    store.append_message(task["id"], "user", "新问题 C")
    store.append_message(task["id"], "assistant", "新回答 C")

    replaying = scripted_client(tool_completions=[])

    async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        seen_messages.append(list(messages))
        return ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")

    replaying.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, replaying, tmp_path)  # 新 runtime = 模拟重启
    asyncio.run(_collect(runtime, task["id"], "继续"))

    messages = seen_messages[-1]
    system_msgs = [m for m in messages if m["role"] == "system"]
    assert any("## Archived Session Summary\n存档摘要" in m["content"] for m in system_msgs)
    payload = json.dumps(messages, ensure_ascii=False)
    assert "近期问题 B" in payload and "新问题 C" in payload
    assert "早期问题 A" not in payload


def test_websearch_tools_not_registered_without_an_api_key(store, scripted_client, echo_tool_registry, tmp_path) -> None:
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

    asyncio.run(_collect(runtime, task["id"], "search something"))

    tool_names = [fn["function"]["name"] for tools in seen_tools for fn in tools]
    assert "echo" in tool_names
    assert "web_search" not in tool_names
    assert "web_extractor" not in tool_names


def test_websearch_tools_registered_with_an_api_key(store, scripted_client, echo_tool_registry, tmp_path) -> None:
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
    runtime = _runtime(
        store, client, tmp_path, tool_registry_factory=lambda: echo_tool_registry, tavily_api_key="tvly-test"
    )
    task = store.create_task("toolcall")

    asyncio.run(_collect(runtime, task["id"], "search something"))

    tool_names = [fn["function"]["name"] for tools in seen_tools for fn in tools]
    assert "web_search" in tool_names
    assert "web_extractor" in tool_names


def test_ensure_skills_only_advertises_added_skills(store, scripted_client, tmp_path, monkeypatch) -> None:
    import runtime as runtime_module
    from skill.models import SkillSummary

    class _FakeSkillClient:
        def __init__(self, url: str) -> None:
            pass

        async def list_skills(self):
            return [
                SkillSummary(name="date", description="dates", added=True, tags=[], usage_count=0),
                SkillSummary(name="csv-to-json", description="csv", added=False, tags=[], usage_count=0),
            ]

    monkeypatch.setattr(runtime_module, "SkillClient", _FakeSkillClient)

    seen_messages: list[list[dict]] = []
    client = scripted_client(tool_completions=[])

    async def spy_astream_with_tools(messages, tools, on_text_delta=None, **kwargs):
        seen_messages.append(list(messages))
        completion = ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")
        if on_text_delta is not None:
            for ch in completion.text:
                await on_text_delta(ch)
        return completion

    client.astream_with_tools = spy_astream_with_tools  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("toolcall")

    asyncio.run(_collect(runtime, task["id"], "hello"))

    system_text = "\n".join(
        m["content"] for msgs in seen_messages for m in msgs if m["role"] == "system"
    )
    assert "<name>date</name>" in system_text
    assert "<name>csv-to-json</name>" not in system_text


def test_ensure_skills_refetches_for_each_new_task(store, scripted_client, tmp_path, monkeypatch) -> None:
    import runtime as runtime_module
    from skill.models import SkillSummary

    call_count = 0

    class _FakeSkillClient:
        def __init__(self, url: str) -> None:
            pass

        async def list_skills(self):
            nonlocal call_count
            call_count += 1
            return [SkillSummary(name="date", description="dates", added=True, tags=[], usage_count=0)]

    monkeypatch.setattr(runtime_module, "SkillClient", _FakeSkillClient)

    client = scripted_client(tool_completions=[
        ToolCompletion(text="ok", requested_tools=[], model_id="mock-model"),
        ToolCompletion(text="ok", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task_a = store.create_task("toolcall")
    task_b = store.create_task("toolcall")

    asyncio.run(_collect(runtime, task_a["id"], "hi"))
    asyncio.run(_collect(runtime, task_b["id"], "hi"))

    assert call_count == 2


def test_stream_reply_skips_suggestions_when_requested(store, scripted_client, tmp_path) -> None:
    client = scripted_client(
        tool_completions=[ToolCompletion(text="你好", requested_tools=[], model_id="mock-model")],
        completions=[Completion(text='["不应该出现的推荐"]', model_id="mock-model")],
    )
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect_kw(runtime, task["id"], "hi", skip_suggestions=True))

    event_types = [e["type"] for e in events]
    assert event_types[-1] == "done"
    assert "suggestions" not in event_types


def test_stream_reply_generates_a_title_on_first_message(store, scripted_client, tmp_path) -> None:
    # 标题生成和跟进问题推荐并行发起、共用同一个 client.acomplete，asyncio 调度顺序不保证
    # 谁先到——按 system prompt 内容路由而不是按队列顺序，两边谁先谁后结果都确定。
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好", requested_tools=[], model_id="mock-model"),
    ])

    async def routed_acomplete(messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
        system = messages[0]["content"]
        if "标题生成器" in system:
            return Completion(text="查询今天日期", model_id="mock-model")
        return Completion(text="[]", model_id="mock-model")

    client.acomplete = routed_acomplete  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "今天是几号？"))

    # 两次 title 事件：user_stored 后立即发的截断兜底版，done 后再发一次模型概括版覆盖它。
    title_events = [{k: v for k, v in e.items() if k != "_id"} for e in events if e["type"] == "title"]
    assert title_events == [
        {"type": "title", "title": "今天是几号？"},
        {"type": "title", "title": "查询今天日期"},
    ]
    assert store.get_task(task["id"])["title"] == "查询今天日期"


def test_stream_reply_does_not_regenerate_title_on_later_messages(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(text="好的", requested_tools=[], model_id="mock-model"),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")

    events = asyncio.run(_collect(runtime, task["id"], "第二条消息"))

    assert "title" not in [e["type"] for e in events]
    assert store.get_task(task["id"])["title"] == "已有标题"


def test_stream_reply_title_generation_failure_keeps_truncated_fallback(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好", requested_tools=[], model_id="mock-model"),
    ])

    async def raising(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
        raise RuntimeError("model down")

    client.acomplete = raising  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    events = asyncio.run(_collect(runtime, task["id"], "一条很长很长的第一条消息"))

    # 只有 user_stored 后立即发的截断兜底版那一次 title 事件；模型调用失败，没有第二次覆盖。
    title_events = [{k: v for k, v in e.items() if k != "_id"} for e in events if e["type"] == "title"]
    assert title_events == [{"type": "title", "title": "一条很长很长的第一条消息"}]
    assert store.get_task(task["id"])["title"] == "一条很长很长的第一条消息"  # 截断兜底未被覆盖


def test_stream_reply_skips_title_generation_when_skip_suggestions_is_true(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[
        ToolCompletion(text="你好", requested_tools=[], model_id="mock-model"),
    ])
    # 不提供 completions：一旦标题生成真的发起了模型调用，fake_acomplete 未被覆盖时
    # 会落到 FakeModelBackend 默认实现（返回空文本）而不是报错——所以改用显式断言调用次数。
    call_count = 0
    original_acomplete = client.acomplete

    async def counting_acomplete(*args: Any, **kwargs: Any) -> Completion:
        nonlocal call_count
        call_count += 1
        return await original_acomplete(*args, **kwargs)

    client.acomplete = counting_acomplete  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    asyncio.run(_collect_kw(runtime, task["id"], "hi", skip_suggestions=True))

    assert call_count == 0
    assert store.get_task(task["id"])["title"] == "hi"


def test_stream_reply_accumulates_tokens_onto_a_passed_in_cancellation_token(store, scripted_client, tmp_path) -> None:
    from core.cancellation import CancellationToken

    client = scripted_client(tool_completions=[
        ToolCompletion(text="ok", requested_tools=[], model_id="mock-model", token_usage={"total_tokens": 42}),
    ])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    cancellation = CancellationToken()

    asyncio.run(_collect_kw(runtime, task["id"], "hi", cancellation=cancellation))

    assert cancellation.tokens_used == 42


def test_model_client_property_exposes_the_underlying_client(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])
    runtime = _runtime(store, client, tmp_path)

    assert runtime.model_client is client


def test_search_client_is_none_without_a_tavily_api_key(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])
    runtime = _runtime(store, client, tmp_path)
    assert runtime.search_client is None


def test_search_client_exposes_the_configured_tavily_client(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])
    runtime = ChatRuntime(
        store, model_client=client, skill_service_url="http://127.0.0.1:1",
        trace_dir=tmp_path / "traces", tavily_api_key="tvly-test",
    )
    assert runtime.search_client is not None


def _mcp_demo_server_config() -> dict:
    demo_server = str(
        Path(__file__).resolve().parent.parent.parent.parent / "packages" / "mcpclient" / "demo_server.py"
    )
    return {"command": sys.executable, "args": [demo_server]}


async def test_enabled_mcp_server_tool_reaches_registry(store, scripted_client, tmp_path) -> None:
    store.create_mcp_server(
        name="weather", transport="stdio", config=_mcp_demo_server_config(),
        cached_tools=[{"name": "get_weather", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
    )
    runtime = _runtime(store, scripted_client(tool_completions=[]), tmp_path)
    task = store.create_task("react")
    await runtime._get_agent(task)
    registry = runtime._registries[task["id"]]
    assert registry.get("get_weather") is not None


async def test_disabled_mcp_server_tool_absent_from_registry(store, scripted_client, tmp_path) -> None:
    created = store.create_mcp_server(
        name="weather", transport="stdio", config=_mcp_demo_server_config(),
        cached_tools=[{"name": "get_weather", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
    )
    store.set_mcp_server_enabled(created["id"], False)
    runtime = _runtime(store, scripted_client(tool_completions=[]), tmp_path)
    task = store.create_task("react")
    await runtime._get_agent(task)
    registry = runtime._registries.get(task["id"])
    assert registry is None or registry.get("get_weather") is None


async def test_a2a_peer_tool_absent_without_url(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])
    runtime = ChatRuntime(
        store, model_client=client, skill_service_url="http://127.0.0.1:1", trace_dir=tmp_path / "traces",
    )
    task = store.create_task("react")
    await runtime._get_agent(task)
    registry = runtime._registries.get(task["id"])
    assert registry is None or registry.get("ask_peer_agent") is None


async def test_a2a_peer_tool_present_with_url(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[])
    runtime = ChatRuntime(
        store, model_client=client, skill_service_url="http://127.0.0.1:1",
        trace_dir=tmp_path / "traces", a2a_peer_url="http://127.0.0.1:8430/",
    )
    task = store.create_task("react")
    await runtime._get_agent(task)
    registry = runtime._registries[task["id"]]
    assert registry.get("ask_peer_agent") is not None


async def test_dispatch_subagent_is_always_registered(store, scripted_client, tmp_path) -> None:
    runtime = _runtime(store, scripted_client(tool_completions=[]), tmp_path)
    task = store.create_task("react")

    await runtime._get_agent(task)

    registry = runtime._registries[task["id"]]
    assert registry.get("dispatch_subagent") is not None


async def test_subagent_tool_registry_includes_the_other_configured_tools(store, scripted_client, tmp_path) -> None:
    runtime = _runtime(
        store, scripted_client(tool_completions=[]), tmp_path, a2a_peer_url="http://127.0.0.1:8430/",
    )
    task = store.create_task("react")

    await runtime._get_agent(task)

    registry = runtime._registries[task["id"]]
    dispatch_tool = registry.get("dispatch_subagent")
    subagent_schema_names = {s["function"]["name"] for s in dispatch_tool._subagent_tools.function_schemas()}
    assert "ask_peer_agent" in subagent_schema_names
    assert "dispatch_subagent" not in subagent_schema_names


def test_aclose_closes_the_model_client(store, tmp_path) -> None:
    client = ModelClient(provider="mock")
    closed = {"count": 0}

    async def fake_aclose() -> None:
        closed["count"] += 1

    client.aclose = fake_aclose  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)

    asyncio.run(runtime.aclose())

    assert closed["count"] == 1


def test_aclose_is_a_noop_when_no_model_client_was_constructed(store) -> None:
    runtime = ChatRuntime(store, model_client=None, skill_service_url="http://127.0.0.1:1")

    asyncio.run(runtime.aclose())  # 懒构造从未发生，不应抛异常


def test_steer_without_active_run_returns_false(store) -> None:
    runtime = ChatRuntime(store, model_client=ModelClient(provider="mock"), skill_service_url="http://127.0.0.1:1")

    assert asyncio.run(runtime.steer("t1", "改用中文")) is False


async def test_steer_appends_a_user_row_and_emits_user_stored(store, scripted_client, tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    client = scripted_client(tool_completions=[])

    async def slow_stream(messages, tools, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        started.set()
        await release.wait()
        return ToolCompletion(text="完成", requested_tools=[], model_id="mock-model")

    client.astream_with_tools = slow_stream  # type: ignore[method-assign]
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")
    store.update_task(task["id"], title="已有标题")

    async def scenario() -> list[dict[str, Any]]:
        gen = runtime.stream_reply(task["id"], "原始问题")
        await gen.__anext__()  # user_stored
        await started.wait()  # 运行已开始，模型阻塞中
        assert await runtime.steer(task["id"], "改用中文") is True
        release.set()
        return [event async for event in gen]

    events = await scenario()

    user_rows = [r for r in store.list_messages(task["id"]) if r["kind"] == "user"]
    assert [r["content"] for r in user_rows] == ["原始问题", "改用中文"]
    # 运行中注入的 user_stored 也通过 SSE 下发（前端据此把乐观泡换成 row-N）
    assert any(e["type"] == "user_stored" for e in events)


class _HangingTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="hang", description="Never returns before the timeout.")

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        await asyncio.sleep(10)
        return ToolOutcome.ok("too late")


class _ExplodingTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="boom", description="Always raises.")

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        raise RuntimeError("kaboom")


def test_registry_enforces_a_tool_timeout(store) -> None:
    runtime = ChatRuntime(
        store,
        model_client=ModelClient(provider="mock"),
        skill_service_url="http://127.0.0.1:1",
        tool_timeout_seconds=0.01,
    )
    registry = runtime._build_registry("t1")
    registry.register(_HangingTool())

    outcome = asyncio.run(registry.acall("hang", {}))

    assert outcome.failure_code == FailureCode.TIMEOUT


def test_registry_trips_the_shared_circuit_breaker_across_tasks(store) -> None:
    runtime = ChatRuntime(
        store,
        model_client=ModelClient(provider="mock"),
        skill_service_url="http://127.0.0.1:1",
        circuit_failure_threshold=2,
    )
    registry = runtime._build_registry("t1")
    registry.register(_ExplodingTool())
    asyncio.run(registry.acall("boom", {}))  # 失败 1
    asyncio.run(registry.acall("boom", {}))  # 失败 2 → 开路

    # 换一个 task 的注册表，共享同一个熔断器：仍是开路状态
    other = runtime._build_registry("t2")
    other.register(_ExplodingTool())
    outcome = asyncio.run(other.acall("boom", {}))

    assert outcome.failure_code == FailureCode.CIRCUIT_OPEN


async def test_request_approval_roundtrip_emits_and_resolves(store) -> None:
    runtime = ChatRuntime(store, model_client=ModelClient(provider="mock"), skill_service_url="http://127.0.0.1:1")
    registry = runtime._build_registry("t1")
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)

    registry.sink = sink
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json='{"x": 1}')
    task = asyncio.create_task(runtime._request_approval("t1", invocation))
    for _ in range(100):  # 等 _request_approval 跑到挂起等待
        if runtime._pending_approvals:
            break
        await asyncio.sleep(0)

    required = next(e for e in events if e["type"] == "approval_required")
    assert required["name"] == "danger"
    assert required["arguments"] == {"x": 1}
    assert runtime.resolve_approval("t1", required["approval_id"], True) is True

    assert await task is True
    assert any(e["type"] == "approval_resolved" and e["approved"] for e in events)


async def test_request_approval_times_out_as_denied(store) -> None:
    runtime = ChatRuntime(
        store,
        model_client=ModelClient(provider="mock"),
        skill_service_url="http://127.0.0.1:1",
        approval_timeout_seconds=0.01,
    )
    registry = runtime._build_registry("t1")

    async def sink(event: dict[str, Any]) -> None:
        return None

    registry.sink = sink
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")

    assert await runtime._request_approval("t1", invocation) is False


async def test_request_approval_is_denied_without_an_active_stream(store) -> None:
    runtime = ChatRuntime(store, model_client=ModelClient(provider="mock"), skill_service_url="http://127.0.0.1:1")
    runtime._build_registry("t1")  # sink 默认 None
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")

    assert await runtime._request_approval("t1", invocation) is False


def test_resolve_approval_rejects_unknown_id_or_wrong_task(store) -> None:
    runtime = ChatRuntime(store, model_client=ModelClient(provider="mock"), skill_service_url="http://127.0.0.1:1")

    assert runtime.resolve_approval("t1", "nope", True) is False


class _ApprovalTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="danger", description="Side-effecting tool.", requires_approval=True)
        self.calls = 0

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        self.calls += 1
        return ToolOutcome.ok("executed")


def _approval_runtime(store, scripted_client, tmp_path):
    registry = ToolRegistry()
    tool = _ApprovalTool()
    registry.register(tool)
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")],
                model_id="mock-model",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock-model"),
        ]
    )
    runtime = _runtime(store, client, tmp_path, tool_registry_factory=lambda: registry)
    return runtime, tool


async def _drive_with_decision(runtime: ChatRuntime, task_id: str, approved: bool) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime.stream_reply(task_id, "go"):
        events.append(event)
        if event["type"] == "approval_required":
            assert runtime.resolve_approval(task_id, event["approval_id"], approved) is True
    return events


async def test_stream_executes_a_gated_tool_after_the_user_approves(store, scripted_client, tmp_path) -> None:
    runtime, tool = _approval_runtime(store, scripted_client, tmp_path)
    task = store.create_task("react")

    events = await _drive_with_decision(runtime, task["id"], True)

    types = [e["type"] for e in events]
    assert "approval_required" in types and "approval_resolved" in types
    assert tool.calls == 1
    assert any(e["type"] == "tool_result" and e.get("result") == "executed" for e in events)
    assert types[-1] == "done"


async def test_stream_denies_a_gated_tool_and_the_turn_continues(store, scripted_client, tmp_path) -> None:
    runtime, tool = _approval_runtime(store, scripted_client, tmp_path)
    task = store.create_task("react")

    events = await _drive_with_decision(runtime, task["id"], False)

    assert tool.calls == 0  # 被拒绝，未执行
    assert events[-1]["type"] == "done"


def test_stream_reply_writes_a_complete_trace_with_task_id(store, scripted_client, tmp_path) -> None:
    client = scripted_client(tool_completions=[ToolCompletion(text="你好", requested_tools=[], model_id="mock-model")])
    runtime = _runtime(store, client, tmp_path)
    task = store.create_task("react")

    asyncio.run(_collect(runtime, task["id"], "hi"))

    traces = list((tmp_path / "traces").glob("run-*.jsonl"))
    assert len(traces) == 1
    events = [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "session_start"
    assert events[0]["payload"]["task_id"] == task["id"]  # HTTP 请求 ↔ trace 关联
    assert events[-1]["event"] == "session_end"
    assert "Session Stats" in traces[0].with_suffix(".html").read_text(encoding="utf-8")
