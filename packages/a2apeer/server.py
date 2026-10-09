"""把一个 core.Agent 实例包成官方 A2A 协议能调用的 server。胶水代码：AgentExecutor 的
两个抽象方法 + 官方 SDK 现成组件（DefaultRequestHandler/InMemoryTaskStore/
add_a2a_routes_to_fastapi 等）的组装，不重新发明协议本身。"""
import uuid

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message, Part, Role
from core.agent import Agent
from fastapi import FastAPI


class OpenTalosAgentExecutor(AgentExecutor):
    """收到一条 A2A 消息就真实调用 agent.arespond()，把回复文本封成 A2A Message 发回去。"""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = next(
            (part.text for part in context.message.parts if part.WhichOneof("content") == "text"), ""
        )
        reply = await self._agent.arespond(text)
        await event_queue.enqueue_event(
            Message(
                message_id=uuid.uuid4().hex, context_id=context.context_id,
                role=Role.ROLE_AGENT, parts=[Part(text=reply)],
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def build_a2a_app(agent: Agent, *, name: str, description: str, port: int) -> FastAPI:
    """组装一个真实可跑的 A2A FastAPI app。port 只用来填 AgentCard 里的
    supported_interfaces.url（client 据此知道该连哪个地址），不是这个函数自己监听端口——
    真正监听端口是调用方用 uvicorn 起 app 时才决定的。"""
    card = AgentCard(
        name=name, description=description, version="0.1.0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        skills=[AgentSkill(id="chat", name="chat", description=description, tags=["chat"])],
        supported_interfaces=[AgentInterface(url=f"http://127.0.0.1:{port}/", protocol_binding="JSONRPC")],
    )
    handler = DefaultRequestHandler(
        agent_executor=OpenTalosAgentExecutor(agent), task_store=InMemoryTaskStore(), agent_card=card
    )
    app = FastAPI()
    add_a2a_routes_to_fastapi(
        app, agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
