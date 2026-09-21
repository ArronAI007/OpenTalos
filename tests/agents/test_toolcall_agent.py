from core.chat_message import ChatMessage
from core.completion import Completion, ToolCompletion, ToolInvocation
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
