from core.protocol import Completion, ToolCompletion, ToolInvocation
from agents.plan_execute_agent import PlanExecuteAgent, RoleConfig


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
    agent = PlanExecuteAgent(name="bot", model_client=client)

    answer = await agent.arespond("plan a trip")

    assert answer == "result two"


async def test_arespond_falls_back_to_a_single_step_when_planning_returns_no_tool_call(scripted_client):
    client = scripted_client(
        completions=[Completion(text="direct answer", model_id="mock")],
        tool_completions=[ToolCompletion(text="no plan tool call", requested_tools=[], model_id="mock")],
    )
    agent = PlanExecuteAgent(name="bot", model_client=client)

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
    agent = PlanExecuteAgent(name="bot", model_client=client, tool_registry=echo_tool_registry)

    answer = await agent.arespond("echo something")

    assert answer == "step done"


async def test_plan_schema_offers_roles_and_parses_assigned_role(scripted_client):
    # Task 4 还没有角色分发逻辑（那是 Task 5），两步都会走本地执行——本地执行在没有
    # tool_registry 时调的是 model_client.acomplete()（走 completions 队列），不是
    # acomplete_with_tools()（走 tool_completions 队列），和现有的
    # test_arespond_plans_then_executes_each_step 是同一个消费规则。
    client = scripted_client(
        completions=[
            Completion(text="step one result", model_id="mock"),
            Completion(text="step two result", model_id="mock"),
        ],
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(
                        call_id="c1", tool_name="propose_steps",
                        arguments_json='{"steps": [{"text": "look it up", "role": "researcher"}, {"text": "write it up"}]}',
                    )
                ],
                model_id="mock",
            ),
        ],
    )
    agent = PlanExecuteAgent(
        name="bot", model_client=client,
        roles=[RoleConfig(name="researcher", description="finds facts", peer_url="http://x")],
    )

    answer = await agent.arespond("plan a trip")

    assert answer == "step two result"


async def test_plan_schema_without_roles_is_unchanged_plain_strings(scripted_client):
    # 没传 roles 时，解析出来的 PlanStep 全部 role=None——老行为完全不变。
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="propose_steps", arguments_json='{"steps": ["step one"]}')
                ],
                model_id="mock",
            ),
        ],
        completions=[Completion(text="result", model_id="mock")],
    )
    agent = PlanExecuteAgent(name="bot", model_client=client)

    answer = await agent.arespond("plan a trip")

    assert answer == "result"
