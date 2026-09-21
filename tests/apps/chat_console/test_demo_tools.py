import pytest

from demo_tools import CalculatorTool
from tool.outcome import FailureCode


@pytest.fixture
def calculator() -> CalculatorTool:
    return CalculatorTool()


async def test_evaluates_basic_arithmetic(calculator):
    outcome = await calculator.acall({"expression": "2 + 2"})
    assert outcome.succeeded
    assert outcome.output == "4"


async def test_respects_operator_precedence_and_parentheses(calculator):
    outcome = await calculator.acall({"expression": "2 * (3 + 4) - 1"})
    assert outcome.succeeded
    assert outcome.output == "13"


async def test_supports_unary_minus(calculator):
    outcome = await calculator.acall({"expression": "-5 + 2"})
    assert outcome.succeeded
    assert outcome.output == "-3"


async def test_rejects_function_calls(calculator):
    outcome = await calculator.acall({"expression": '__import__("os").system("echo pwned")'})
    assert not outcome.succeeded
    assert outcome.failure_code == FailureCode.INVALID_ARGUMENTS


async def test_rejects_name_lookups(calculator):
    outcome = await calculator.acall({"expression": "os.getcwd"})
    assert not outcome.succeeded


async def test_rejects_malformed_syntax(calculator):
    outcome = await calculator.acall({"expression": "2 +"})
    assert not outcome.succeeded


def test_exposes_a_single_expression_parameter(calculator):
    params = calculator.parameters()
    assert [p.name for p in params] == ["expression"]
    assert params[0].required is True
