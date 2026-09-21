from dataclasses import dataclass

import pytest

from opentalos.core_types import TenantContext, ToolCall, ToolDefinition, ToolResult
from opentalos.tool_registry.in_memory import InMemoryToolRegistry


@dataclass
class _EchoTool:
    definition: ToolDefinition

    async def execute(self, input, ctx: TenantContext) -> ToolResult:
        return ToolResult(id="ignored", output=input)


@dataclass
class _ThrowingTool:
    definition: ToolDefinition

    async def execute(self, input, ctx: TenantContext) -> ToolResult:
        raise ValueError("boom")


CTX = TenantContext(tenant_id="t1", session_id="s1")


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description="d", input_schema={"type": "object"})


@pytest.mark.asyncio
async def test_register_and_list():
    registry = InMemoryToolRegistry()
    registry.register(_EchoTool(definition=_definition("echo")))
    assert [d.name for d in registry.list_definitions()] == ["echo"]
    assert registry.get("echo") is not None


@pytest.mark.asyncio
async def test_execute_registered_tool():
    registry = InMemoryToolRegistry()
    registry.register(_EchoTool(definition=_definition("echo")))
    result = await registry.execute(ToolCall(id="c1", name="echo", input="hi"), CTX)
    assert result.output == "hi"
    assert result.is_error is None


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error_result():
    registry = InMemoryToolRegistry()
    result = await registry.execute(ToolCall(id="c1", name="missing", input=None), CTX)
    assert result.is_error is True
    assert "missing" in result.output


@pytest.mark.asyncio
async def test_execute_tool_that_throws_is_caught():
    registry = InMemoryToolRegistry()
    registry.register(_ThrowingTool(definition=_definition("boom")))
    result = await registry.execute(ToolCall(id="c1", name="boom", input=None), CTX)
    assert result.is_error is True
    assert "boom" in result.output


@pytest.mark.asyncio
async def test_execute_overrides_tool_own_id_with_call_id():
    registry = InMemoryToolRegistry()
    registry.register(_EchoTool(definition=_definition("echo")))
    result = await registry.execute(ToolCall(id="the-real-id", name="echo", input="x"), CTX)
    assert result.id == "the-real-id"
