import ast
import operator
from typing import Any

from tool.outcome import FailureCode, ToolOutcome
from tool.tool import Tool, ToolParameter

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    """只认数字字面量和 +-*/%** 这几个算术节点，拒绝一切其它 AST 节点（函数调用、属性访问等）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


class CalculatorTool(Tool):
    """演示用的安全算术求值工具（不用 eval，只解析 AST 里认识的算术节点）。"""

    def __init__(self) -> None:
        super().__init__(name="calculator", description="Evaluate a basic arithmetic expression, e.g. '2 * (3 + 4)'.")

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="expression", type="string", description="An arithmetic expression to evaluate.")]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        expression = arguments["expression"]
        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree.body)
        except Exception as error:
            return ToolOutcome.error(f"Could not evaluate '{expression}': {error}", code=FailureCode.INVALID_ARGUMENTS)
        return ToolOutcome.ok(str(result))
