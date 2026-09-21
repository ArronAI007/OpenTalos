from core.completion import ToolCompletion, ToolInvocation
from agents.react_agent import STEP_LIMIT_MESSAGE, ReActAgent


async def test_arespond_returns_text_when_the_model_calls_no_tools(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="direct answer", requested_tools=[], model_id="mock")])
    agent = ReActAgent(name="bot", model_client=client)

    answer = await agent.arespond("what's 2+2")

    assert answer == "direct answer"


async def test_arespond_uses_a_tool_then_finishes(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c2", tool_name="finish", arguments_json='{"final_answer": "hi echoed"}')
                ],
                model_id="mock",
            ),
        ]
    )
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    answer = await agent.arespond("echo hi then finish")

    assert answer == "hi echoed"


async def test_arespond_falls_back_to_the_step_limit_message(scripted_client, echo_tool_registry):
    looping_call = ToolCompletion(
        text=None,
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
        model_id="mock",
    )
    client = scripted_client(tool_completions=[looping_call, looping_call])
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=2)

    answer = await agent.arespond("loop forever")

    assert answer == STEP_LIMIT_MESSAGE


async def test_finish_tool_is_offered_even_without_a_tool_registry(scripted_client):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="finish", arguments_json='{"final_answer": "42"}')
                ],
                model_id="mock",
            )
        ]
    )
    agent = ReActAgent(name="bot", model_client=client)

    answer = await agent.arespond("what is the answer")

    assert answer == "42"
