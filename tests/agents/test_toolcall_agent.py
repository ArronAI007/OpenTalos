import json
from typing import Any

from context import OutputTrimmer
from core.protocol import ChatMessage, Completion, ToolCompletion, ToolInvocation
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter
from agents.toolcall_agent import ToolCallingAgent


async def test_arespond_without_tools_just_completes(scripted_client):
    client = scripted_client(completions=[Completion(text="hi there", model_id="mock")])
    agent = ToolCallingAgent(name="bot", model_client=client)

    answer = await agent.arespond("hi")

    assert answer == "hi there"
    history = agent.history_snapshot()
    assert [m.content for m in history] == ["hi", "hi there"]


async def test_arespond_with_tools_executes_and_returns_final_text(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="all done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ToolCallingAgent(name="bot", model_client=client, tool_registry=echo_tool_registry)

    answer = await agent.arespond("say hi via the echo tool")

    assert answer == "all done"


async def test_tool_result_recorded_into_history(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="all done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ToolCallingAgent(name="bot", model_client=client, tool_registry=echo_tool_registry)

    await agent.arespond("say hi via the echo tool")

    tool_msgs = [m for m in agent.history_snapshot() if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "echoed: hi"
    assert tool_msgs[0].metadata["tool_call_id"] == "c1"
    assert tool_msgs[0].metadata["tool_name"] == "echo"
    assert tool_msgs[0].metadata["arguments"] == '{"text": "hi"}'


async def test_arespond_records_history_that_seeds_the_next_turn(scripted_client):
    client = scripted_client(
        completions=[Completion(text="first reply", model_id="mock"), Completion(text="second reply", model_id="mock")]
    )
    agent = ToolCallingAgent(name="bot", model_client=client, system_prompt="Be terse.")

    await agent.arespond("first question")
    await agent.arespond("second question")

    history = agent.history_snapshot()
    assert [m.content for m in history] == ["first question", "first reply", "second question", "second reply"]
    assert isinstance(history[0], ChatMessage)


async def test_arespond_logs_model_and_tool_events_when_tracing_is_enabled(scripted_client, echo_tool_registry, tmp_path):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="all done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ToolCallingAgent(
        name="bot", model_client=client, tool_registry=echo_tool_registry, trace_dir=str(tmp_path)
    )

    await agent.arespond("say hi via the echo tool")
    stats = agent.recorder.finalize()

    lines = [json.loads(line) for line in agent.recorder.jsonl_path.read_text(encoding="utf-8").splitlines()]
    event_types = [line["event"] for line in lines]
    assert event_types == ["model_output", "tool_call", "tool_result", "model_output"]
    assert stats["tool_calls"] == {"echo": 1}


class _ChattyTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="chatty", description="Returns 50 lines.")

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome.ok("\n".join(f"line {i}" for i in range(50)))


async def test_output_trimmer_passed_to_the_agent_reaches_the_tool_call_path(scripted_client, tmp_path):
    registry = ToolRegistry()
    registry.register(_ChattyTool())
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="chatty", arguments_json="{}")],
                model_id="mock",
            ),
            ToolCompletion(text="all done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ToolCallingAgent(
        name="bot",
        model_client=client,
        tool_registry=registry,
        output_trimmer=OutputTrimmer(max_lines=5, max_bytes=1_000_000, output_dir=str(tmp_path)),
    )

    await agent.arespond("call the chatty tool")

    assert len(list(tmp_path.glob("chatty_*.json"))) == 1
