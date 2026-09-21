from core.completion import Completion, ToolCompletion, ToolInvocation
from agents.planner_agent import PlannerAgent


async def test_arespond_plans_then_executes_each_step(scripted_client):
    # No tool_registry -> _run_steps calls plain acomplete (not acomplete_with_tools) per step.
    client = scripted_client(
        completions=[
            Completion(text="result one", model_id="mock"),
            Completion(text="result two", model_id="mock"),
        ],
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(
                        call_id="c1", tool_name="propose_steps", arguments_json='{"steps": ["step one", "step two"]}'
                    )
                ],
                model_id="mock",
            ),
        ],
    )
    agent = PlannerAgent(name="bot", model_client=client)

    answer = await agent.arespond("plan a trip")

    assert answer == "result two"


async def test_arespond_falls_back_to_a_single_step_when_planning_returns_no_tool_call(scripted_client):
    client = scripted_client(
        completions=[Completion(text="direct answer", model_id="mock")],
        tool_completions=[ToolCompletion(text="no plan tool call", requested_tools=[], model_id="mock")],
    )
    agent = PlannerAgent(name="bot", model_client=client)

    answer = await agent.arespond("simple question")

    assert answer == "direct answer"


async def test_step_execution_uses_the_tool_registry(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="propose_steps", arguments_json='{"steps": ["echo hi"]}')
                ],
                model_id="mock",
            ),
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c2", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="step done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = PlannerAgent(name="bot", model_client=client, tool_registry=echo_tool_registry)

    answer = await agent.arespond("echo something")

    assert answer == "step done"
