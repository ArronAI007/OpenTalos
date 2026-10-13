"""真实调用大模型的自测（FR-004/FR-005/FR-006）：验证 packages/core 的 agent loop 在接上真实配
置好的大模型服务时，确实能完成纯文本往返 + 工具调用意图识别两条路径，而不只是在用假数据跑通。

按是否配置 MODEL_API_KEY 自动跳过——没配凭据时本模块里的所有测试都给出清晰的跳过说明，不污染常规
测试套件的红绿状态；超时/限流（SC-003）同样按 skip 处理，不与"agent loop 逻辑有 bug"混淆。
"""
import asyncio
import os

import pytest

from core.agent_loop import run_tool_turn
from core.model import ModelClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("MODEL_API_KEY"),
    reason="未配置 MODEL_API_KEY，跳过真实模型自测",
)

_TIMEOUT_SECONDS = 60


class _FakeToolExecutor:
    """只认一个固定工具名的最小假对象，满足 ToolExecutor 形状；不依赖真实的 tool 包。"""

    def __init__(self, tool_name: str = "get_current_time") -> None:
        self._tool_name = tool_name
        self.called_with: list[dict] = []

    def get(self, name: str):
        return None  # 不要求审批

    async def acall(self, name: str, arguments: dict, *, call_id: str | None = None):
        self.called_with.append(arguments)
        from core.protocols import ToolCallResult

        return ToolCallResult(succeeded=True, duration_ms=1.0, output="2026-01-01T00:00:00")

    def function_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self._tool_name,
                    "description": "Return the current time.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


async def test_core_completes_a_real_plain_text_round_trip():
    client = ModelClient()
    messages = [{"role": "user", "content": "Reply with exactly the single word: pong"}]

    try:
        answer = await asyncio.wait_for(
            run_tool_turn(client, messages, None, 1), timeout=_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        pytest.skip("大模型服务超时/不可用")

    print(f"\n[real model reply] {answer!r}")
    assert isinstance(answer, str)
    assert answer.strip()


async def test_core_recognizes_a_real_tool_call_intent():
    client = ModelClient()
    tool_registry = _FakeToolExecutor()
    messages = [
        {
            "role": "user",
            "content": "You must call the get_current_time tool to answer. "
            "Call it now, then tell the user the time.",
        }
    ]

    try:
        answer = await asyncio.wait_for(
            run_tool_turn(client, messages, tool_registry, 3), timeout=_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        pytest.skip("大模型服务超时/不可用")

    print(f"\n[real model reply] {answer!r}")
    assert tool_registry.called_with, "模型应该请求调用 get_current_time，但 core 没有转发这次调用"
