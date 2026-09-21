from opentalos.core_types import (
    Checkpoint,
    Message,
    ModelRequest,
    TextDeltaChunk,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


def test_message_defaults():
    msg = Message(role="user", content="你好")
    assert msg.tool_calls is None
    assert msg.images is None


def test_message_with_images_and_tool_calls():
    call = ToolCall(id="c1", name="lookup", input={"pair": "USD/CNY"})
    msg = Message(role="assistant", content="", tool_calls=[call], images=["data:image/png;base64,abc"])
    assert msg.tool_calls[0].name == "lookup"
    assert msg.images == ["data:image/png;base64,abc"]


def test_tool_definition_optional_fields():
    definition = ToolDefinition(name="t", description="d", input_schema={"type": "object"})
    assert definition.kind is None
    assert definition.dangerous is None


def test_model_response_chunk_discriminated_union():
    chunk = TextDeltaChunk(type="text_delta", text_delta="你好")
    assert chunk.type == "text_delta"


def test_model_request_round_trip():
    request = ModelRequest(messages=[Message(role="user", content="hi")])
    data = request.model_dump()
    restored = ModelRequest.model_validate(data)
    assert restored.messages[0].content == "hi"


def test_checkpoint_required_fields():
    checkpoint = Checkpoint(
        graph_id="g1",
        run_id="run-1",
        tenant_id="tenant-a",
        session_id="session-1",
        node_cursor="start",
        state={},
        pending_yields=[],
        status="running",
        created_at="2026-09-21T00:00:00.000Z",
        cancel_requested=False,
    )
    assert checkpoint.steer_message is None
    assert checkpoint.error is None


def test_tool_result_construction():
    result = ToolResult(id="c1", output="ok")
    assert result.is_error is None
