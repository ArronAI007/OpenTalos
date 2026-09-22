from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter


class _EchoTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="echo", description="Echoes the given text back.")

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="text", type="string", description="Text to echo"),
            ToolParameter(name="shout", type="boolean", description="Uppercase the output", required=False),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        text = arguments["text"]
        if arguments.get("shout"):
            text = text.upper()
        return ToolOutcome.ok(text)


async def test_acall_returns_expected_output():
    tool = _EchoTool()
    outcome = await tool.acall({"text": "hi"})
    assert outcome.output == "hi"


def test_validate_returns_none_when_required_arguments_present():
    tool = _EchoTool()
    assert tool.validate({"text": "hi"}) is None


def test_validate_reports_missing_required_arguments():
    tool = _EchoTool()
    error = tool.validate({})
    assert error == "Missing required argument(s): text"


def test_validate_ignores_missing_optional_arguments():
    tool = _EchoTool()
    assert tool.validate({"text": "hi"}) is None


def test_to_function_schema_shape():
    tool = _EchoTool()
    schema = tool.to_function_schema()
    assert schema == {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echoes the given text back.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to echo"},
                    "shout": {"type": "boolean", "description": "Uppercase the output"},
                },
                "required": ["text"],
            },
        },
    }


def test_to_function_schema_includes_enum_when_present():
    class _ChoiceTool(Tool):
        def __init__(self) -> None:
            super().__init__(name="choice", description="Pick one.")

        def parameters(self) -> list[ToolParameter]:
            return [ToolParameter(name="option", type="string", description="Pick", enum=["a", "b"])]

        async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
            return ToolOutcome.ok(arguments["option"])

    schema = _ChoiceTool().to_function_schema()
    assert schema["function"]["parameters"]["properties"]["option"]["enum"] == ["a", "b"]


def test_to_function_schema_renders_items_for_array_parameters():
    class _BatchTool(Tool):
        def __init__(self) -> None:
            super().__init__(name="batch", description="Run on many.")

        def parameters(self) -> list[ToolParameter]:
            return [ToolParameter(name="items_to_run", type="array", description="Values", items="string")]

        async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
            return ToolOutcome.ok("ok")

    schema = _BatchTool().to_function_schema()
    prop = schema["function"]["parameters"]["properties"]["items_to_run"]
    assert prop == {"type": "array", "description": "Values", "items": {"type": "string"}}
