"""生产入口：uv run uvicorn a2apeer.main:app --port 8430。包一个真实的、不挂任何工具的
ToolCallingAgent——这就是"被调用的那个 agent"，复用 .env 里已有的 MODEL_* 配置，不需要
新配置。没有自动化测试，见本文件所在 Task 的说明；正确性由真机验证确认。"""
from agents.builder import build_agent
from core.model import ModelClient

from .server import build_a2a_app

_agent = build_agent("toolcall", "a2a-peer", ModelClient())
app = build_a2a_app(
    _agent, name="OpenTalos Peer",
    description="A plain conversational OpenTalos agent, reachable via A2A.", port=8430,
)
