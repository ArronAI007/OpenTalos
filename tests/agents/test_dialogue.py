from core.chat_message import ChatMessage
from core.completion import Completion, ToolCompletion, ToolInvocation
from agents.dialogue import build_reply_message, run_tool_turn, seed_messages


def test_seed_messages_includes_system_history_and_query():
    history = [ChatMessage(content="hi", role="user"), ChatMessage(content="hello", role="assistant")]
    messages = seed_messages("Be nice.", history, "what's next?")

    assert messages[0] == {"role": "system", "content": "Be nice."}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert messages[2] == {"role": "assistant", "content": "hello"}
    assert messages[3] == {"role": "user", "content": "what's next?"}


def test_seed_messages_omits_system_block_when_no_prompt():
    messages = seed_messages(None, [], "hi")
    assert messages == [{"role": "user", "content": "hi"}]


def test_build_reply_message_shapes_tool_calls_for_the_wire():
    invocation = ToolInvocation(call_id="call_1", tool_name="echo", arguments_json='{"text": "hi"}')
    message = build_reply_message("thinking...", [invocation])

    assert message["role"] == "assistant"
    assert message["content"] == "thinking..."
    assert message["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "hi"}'}}
    ]


async def test_run_tool_turn_without_registry_just_completes(scripted_client):
    client = scripted_client(completions=[Completion(text="hi there", model_id="mock")])
    answer = await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3)
    assert answer == "hi there"


async def test_run_tool_turn_executes_a_tool_then_returns_final_text(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    messages = [{"role": "user", "content": "say hi"}]

    answer = await run_tool_turn(client, messages, echo_tool_registry, 3)

    assert answer == "done"
    # assistant tool-call message + tool result message got appended
    assert messages[-2]["role"] == "assistant"
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "echoed: hi"}


async def test_run_tool_turn_falls_back_to_plain_complete_after_exhausting_iterations(scripted_client, echo_tool_registry):
    looping_tool_call = ToolCompletion(
        text=None,
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
        model_id="mock",
    )
    client = scripted_client(
        completions=[Completion(text="giving up", model_id="mock")],
        tool_completions=[looping_tool_call, looping_tool_call],
    )

    answer = await run_tool_turn(client, [{"role": "user", "content": "loop forever"}], echo_tool_registry, 2)

    assert answer == "giving up"


async def test_run_tool_turn_reports_invalid_tool_arguments(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json="not json")],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    messages: list[dict] = [{"role": "user", "content": "hi"}]

    await run_tool_turn(client, messages, echo_tool_registry, 3)

    tool_message = messages[-1]
    assert tool_message["role"] == "tool"
    assert "Invalid arguments" in tool_message["content"]
