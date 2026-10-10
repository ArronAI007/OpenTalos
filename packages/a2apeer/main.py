"""生产入口：uv run uvicorn a2apeer.main:app --port <PORT>。默认包一个通用的、不挂任何
工具的 ToolCallingAgent；通过 ROLE_NAME/ROLE_SYSTEM_PROMPT/ROLE_AGENT_TYPE/PORT 环境变量
可以把同一份代码配置成任意角色的 peer 进程——每个角色各自起一个独立进程，不需要给每个
角色单独写一份入口脚本。复用 .env 里已有的 MODEL_* 配置，不需要新配置。没有自动化测试，
正确性由真机验证确认。"""
import os

from agents.builder import build_agent
from core.model import ModelClient

from .server import build_a2a_app

_ROLE_NAME = os.environ.get("ROLE_NAME", "OpenTalos Peer")
_ROLE_SYSTEM_PROMPT = os.environ.get("ROLE_SYSTEM_PROMPT")
_ROLE_AGENT_TYPE = os.environ.get("ROLE_AGENT_TYPE", "toolcall")
_PORT = int(os.environ.get("PORT", "8430"))

_agent = build_agent(_ROLE_AGENT_TYPE, "a2a-peer", ModelClient(), system_prompt=_ROLE_SYSTEM_PROMPT)
app = build_a2a_app(
    _agent, name=_ROLE_NAME,
    description=f"An OpenTalos agent in the '{_ROLE_NAME}' role, reachable via A2A.", port=_PORT,
)
