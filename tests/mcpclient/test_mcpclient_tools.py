"""MCPTool 的单测：_json_schema_to_parameters 用构造的 JSON Schema（纯函数，不需要真实连接），
acall() 用 Task 1 的真实 demo server（stdio）。"""
import sys
from pathlib import Path

from tool.outcome import OutcomeStatus

from mcpclient.client import MCPServerConfig, MCPToolInfo
from mcpclient.tools import MCPTool, _json_schema_to_parameters

_DEMO_SERVER = str(Path(__file__).resolve().parent.parent.parent / "packages" / "mcpclient" / "demo_server.py")


class TestJsonSchemaToParameters:
    def test_required_and_optional_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"},
                "unit": {"type": "string", "enum": ["c", "f"]},
            },
            "required": ["city"],
        }
        params = _json_schema_to_parameters(schema)
        by_name = {p.name: p for p in params}
        assert by_name["city"].required is True
        assert by_name["city"].type == "string"
        assert by_name["city"].description == "城市名"
        assert by_name["unit"].required is False
        assert by_name["unit"].enum == ["c", "f"]

    def test_array_field_carries_items_type(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            "required": [],
        }
        params = _json_schema_to_parameters(schema)
        assert params[0].items == "string"


class TestMCPTool:
    def _tool(self) -> MCPTool:
        server_config = MCPServerConfig(transport="stdio", command=sys.executable, args=[_DEMO_SERVER])
        tool_info = MCPToolInfo(
            name="get_weather", description="Get weather",
            input_schema={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        )
        return MCPTool(server_config, tool_info)

    def test_name_and_description_come_from_tool_info(self) -> None:
        tool = self._tool()
        assert tool.name == "get_weather"
        assert tool.description == "Get weather"

    def test_parameters_reflects_input_schema(self) -> None:
        params = self._tool().parameters()
        assert params[0].name == "city"
        assert params[0].required is True

    async def test_acall_returns_real_result(self) -> None:
        outcome = await self._tool().acall({"city": "Beijing"})
        assert outcome.status == OutcomeStatus.OK
        assert "Beijing" in outcome.output

    async def test_acall_failure_becomes_error_outcome(self) -> None:
        bad_server = MCPServerConfig(transport="stdio", command="no-such-executable-xyz", args=[])
        tool = MCPTool(bad_server, MCPToolInfo(name="x", description="", input_schema={}))
        outcome = await tool.acall({})
        assert outcome.status == OutcomeStatus.ERROR
