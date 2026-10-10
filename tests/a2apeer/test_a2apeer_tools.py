"""A2ATool 的单测：parameters()/name/description 是纯函数检查；acall() 复用真实 demo_server.py
（demo_peer fixture 来自同目录的 conftest.py，见 Task 1）。"""
from tool.outcome import OutcomeStatus

from a2apeer.tools import A2ATool


class TestA2ATool:
    def test_name_and_description(self) -> None:
        tool = A2ATool("http://127.0.0.1:1/")
        assert tool.name == "ask_peer_agent"
        assert "A2A" in tool.description

    def test_output_is_marked_untrusted(self) -> None:
        assert A2ATool("http://127.0.0.1:1/").untrusted_output is True

    def test_parameters(self) -> None:
        params = A2ATool("http://127.0.0.1:1/").parameters()
        assert params[0].name == "question"
        assert params[0].required is True

    async def test_acall_returns_real_result(self, demo_peer: str) -> None:
        outcome = await A2ATool(demo_peer).acall({"question": "hi"})
        assert outcome.status == OutcomeStatus.OK
        assert outcome.output == "HELLO FROM PEER"

    async def test_acall_failure_becomes_error_outcome(self) -> None:
        outcome = await A2ATool("http://127.0.0.1:1/").acall({"question": "hi"})
        assert outcome.status == OutcomeStatus.ERROR
