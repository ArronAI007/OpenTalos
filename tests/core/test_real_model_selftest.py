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
from core.protocol import AgentEvent, EventKind

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


async def test_core_pi_alignment_capabilities_fire_on_a_real_tool_call_run():
    """SC-008：真机验证事件总线/finishTurn 两项核心能力在真实模型往返里确实被触发过（而不是
    只能在单元测试里观察到）。steering/follow-up/消息分层/prepare_request/thinking_level 的真
    机集成已经被 ReActAgent 自身的单元测试（scripted_client）充分覆盖，这里只加真实模型这一个
    维度，不重复全部场景。
    """
    client = ModelClient()
    client.thinking_level = "off"  # 显式验证 off 不会让请求失败（FR-018）
    tool_registry = _FakeToolExecutor()
    messages = [
        {
            "role": "user",
            "content": "You must call the get_current_time tool to answer. "
            "Call it now, then tell the user the time.",
        }
    ]

    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    finish_turn_calls: list[bool] = []

    async def finish_turn(context):
        finish_turn_calls.append(bool(context.completion.requested_tools))
        return None  # 不覆盖默认调度，只验证真的被调用过

    try:
        answer = await asyncio.wait_for(
            run_tool_turn(
                client, messages, tool_registry, 3, emit=emit, agent_name="selftest", finish_turn=finish_turn
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        pytest.skip("大模型服务超时/不可用")

    print(f"\n[real model reply] {answer!r}")
    assert tool_registry.called_with, "模型应该请求调用 get_current_time，但 core 没有转发这次调用"

    kinds = [e.kind for e in events]
    assert kinds[0] == EventKind.TURN_START
    assert EventKind.TOOL_EXECUTION_START in kinds and EventKind.TOOL_EXECUTION_END in kinds
    assert all(e.agent_name == "selftest" for e in events)
    assert finish_turn_calls, "finish_turn 应该在真实运行里被调用过至少一次"
