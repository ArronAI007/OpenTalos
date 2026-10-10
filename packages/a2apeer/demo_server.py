"""自动化测试专用的 A2A server——包一个用脚本化假 ModelClient 驱动的 agent，回复内容由
--reply 参数固定，不碰真实模型/真实网络。真机验证/生产使用走 main.py（那个包的是真实
ModelClient）。"""
import argparse
from typing import Any

import uvicorn
from agents.builder import build_agent
from core.model import ModelClient
from core.protocol import ToolCompletion

from a2apeer.server import build_a2a_app


def _scripted_model_client(reply: str) -> ModelClient:
    client = ModelClient(provider="mock")

    # 现在唯一的 agent 实现是 ReActAgent，它总是走 acomplete_with_tools（即使没有任何
    # 工具可用，ReAct 自带的 finish 工具约定也会让它走这条路径）——不再是旧 ToolCallingAgent
    # 那种"没有 tool_registry 就走 acomplete"的分支，mock 对象要跟着换。
    async def fake_acomplete_with_tools(
        messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str | dict = "auto", **kwargs: Any
    ) -> ToolCompletion:
        return ToolCompletion(text=reply, requested_tools=[], model_id="mock-model")

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]
    return client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--reply", default="SCRIPTED_REPLY")
    args = parser.parse_args()
    agent = build_agent("a2a-demo", _scripted_model_client(args.reply))
    app = build_a2a_app(agent, name="demo", description="demo peer for automated tests", port=args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
