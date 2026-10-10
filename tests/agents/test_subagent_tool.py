from core.protocol import ToolCompletion, ToolInvocation
from agents.subagent_tool import DispatchSubagentTool
from tool.outcome import OutcomeStatus
from tool.registry import ToolRegistry


async def test_acall_builds_a_subagent_and_returns_its_answer(scripted_client):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(text=None, requested_tools=[
                ToolInvocation(call_id="c1", tool_name="finish", arguments_json='{"final_answer": "sub answer"}')
            ], model_id="mock"),
        ],
    )
    tool = DispatchSubagentTool(client, ToolRegistry())

    outcome = await tool.acall({"description": "look something up", "prompt": "what is 2+2"})

    assert outcome.status == OutcomeStatus.OK
    assert outcome.output == "sub answer"


async def test_subagent_tool_registry_does_not_include_dispatch_subagent_itself(scripted_client):
    # 子 agent 自己的工具注册表（构造 DispatchSubagentTool 时传入的那个）里不应该有
    # dispatch_subagent——否则子 agent 能递归再分派，违反设计。这个测试直接检查传入的
    # registry 本身，不需要真的驱动一轮模型调用。
    registry = ToolRegistry()
    client = scripted_client(tool_completions=[])
    tool = DispatchSubagentTool(client, registry)

    assert "dispatch_subagent" not in {schema["function"]["name"] for schema in registry.function_schemas()}
    assert tool.name == "dispatch_subagent"


async def test_acall_wraps_a_failing_subagent_as_a_tool_error(scripted_client):
    # scripted_client 的 tool_completions 传空列表是假值，不会装上脚本化的 fake 方法——直接
    # monkeypatch acomplete_with_tools（ReActAgent 在没有 on_text_delta 时就调这个方法）
    # 让子 agent 的模型调用本身失败，这是比"让脚本化队列耗尽"更直接可靠的触发方式。
    client = scripted_client(tool_completions=[ToolCompletion(text="unused", requested_tools=[], model_id="mock")])

    async def boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    client.acomplete_with_tools = boom
    tool = DispatchSubagentTool(client, ToolRegistry())

    outcome = await tool.acall({"description": "d", "prompt": "p"})

    assert outcome.status == OutcomeStatus.ERROR
    assert "RuntimeError" in outcome.output
    assert "model unavailable" in outcome.output
