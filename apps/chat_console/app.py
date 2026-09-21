"""Gradio 前端：跟 packages/agents 里的四种 Agent 聊天，同时能看每一轮的调用轨迹。

跑之前配好模型环境变量（跟 packages/core/model_client.py 读的一样）：
    MODEL_PROVIDER=anthropic MODEL_API_KEY=... MODEL_NAME=... uv run python apps/chat_console/app.py
没配置也能启动，聊天时会在界面上提示需要设置什么。
"""

import sys
from pathlib import Path

_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

import gradio as gr
from demo_tools import CalculatorTool

from agents.builder import AGENT_TYPES, build_agent
from core.agent import Agent
from core.errors import SettingsError
from core.model_client import ModelClient
from observability.stats import summarize
from tool.registry import ToolRegistry

AGENT_NAME = "chat-console"
TRACE_DIR = Path(__file__).resolve().parent / "traces"

_model_client: ModelClient | None = None
_model_client_error: str | None = None


def _get_model_client() -> tuple[ModelClient | None, str | None]:
    global _model_client, _model_client_error
    if _model_client is not None or _model_client_error is not None:
        return _model_client, _model_client_error
    try:
        _model_client = ModelClient()
    except SettingsError as error:
        _model_client_error = str(error)
    return _model_client, _model_client_error


def _make_agent(agent_type: str, use_calculator: bool) -> tuple[Agent | None, str | None]:
    client, error = _get_model_client()
    if client is None:
        return None, error

    tool_registry = None
    if use_calculator:
        tool_registry = ToolRegistry()
        tool_registry.register(CalculatorTool())

    agent = build_agent(agent_type, AGENT_NAME, client, tool_registry=tool_registry, trace_dir=str(TRACE_DIR))
    return agent, None


def _status_text(agent: Agent | None, agent_type: str) -> str:
    if agent is None or agent.recorder is None:
        return f"Agent type: **{agent_type}** · no active trace session"
    return f"Agent type: **{agent_type}** · trace session `{agent.recorder.session_id}`"


async def respond(message: str, chat_history: list[dict], agent_state: Agent | None, agent_type: str, use_calculator: bool):
    chat_history = list(chat_history or [])
    message = (message or "").strip()
    if not message:
        return chat_history, "", agent_state, _status_text(agent_state, agent_type)

    agent = agent_state
    if agent is None or not isinstance(agent, AGENT_TYPES[agent_type]):
        agent, error = _make_agent(agent_type, use_calculator)
        if agent is None:
            chat_history.append({"role": "user", "content": message})
            chat_history.append(
                {"role": "assistant", "content": f"Cannot reach the model: {error}\n\nSet MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME and restart."}
            )
            return chat_history, "", agent_state, "Model is not configured."

    chat_history.append({"role": "user", "content": message})
    try:
        answer = await agent.arespond(message)
    except Exception as error:  # noqa: BLE001 - surface any failure in the chat instead of crashing the app
        answer = f"Error while responding: {error}"
    chat_history.append({"role": "assistant", "content": answer})

    return chat_history, "", agent, _status_text(agent, agent_type)


def reset_conversation(agent_state: Agent | None):
    if agent_state is not None and agent_state.recorder is not None:
        agent_state.recorder.finalize()
    return [], None, {}, [], None, "No active trace session."


def refresh_trace(agent_state: Agent | None):
    if agent_state is None or agent_state.recorder is None:
        return {}, [], None
    events = agent_state.recorder.events()
    stats = summarize(events)
    return stats, events, str(agent_state.recorder.jsonl_path)


with gr.Blocks(title="OpenTalos Chat Console") as demo:
    agent_state = gr.State(None)

    gr.Markdown("# OpenTalos Chat Console")

    with gr.Row():
        agent_type = gr.Dropdown(choices=list(AGENT_TYPES), value="toolcall", label="Agent type")
        use_calculator = gr.Checkbox(value=True, label="Enable demo calculator tool")
        new_conversation_btn = gr.Button("New conversation")

    status = gr.Markdown("No active trace session.")

    with gr.Tabs():
        with gr.Tab("Chat"):
            chatbot = gr.Chatbot(label="Conversation", height=450)
            with gr.Row():
                msg = gr.Textbox(placeholder="Ask something...", label="Message", scale=4)
                send_btn = gr.Button("Send", scale=1)

        with gr.Tab("Trace"):
            gr.Markdown("Every model call and tool call/result for the current agent, updated after each turn.")
            refresh_btn = gr.Button("Refresh")
            stats_json = gr.JSON(label="Session stats")
            events_json = gr.JSON(label="Event log")
            trace_file = gr.File(label="Download raw JSONL trace")

    trace_outputs = [stats_json, events_json, trace_file]

    send_btn.click(
        respond,
        inputs=[msg, chatbot, agent_state, agent_type, use_calculator],
        outputs=[chatbot, msg, agent_state, status],
    ).then(refresh_trace, inputs=[agent_state], outputs=trace_outputs)

    msg.submit(
        respond,
        inputs=[msg, chatbot, agent_state, agent_type, use_calculator],
        outputs=[chatbot, msg, agent_state, status],
    ).then(refresh_trace, inputs=[agent_state], outputs=trace_outputs)

    refresh_btn.click(refresh_trace, inputs=[agent_state], outputs=trace_outputs)

    reset_outputs = [chatbot, agent_state, stats_json, events_json, trace_file, status]
    new_conversation_btn.click(reset_conversation, inputs=[agent_state], outputs=reset_outputs)
    agent_type.change(reset_conversation, inputs=[agent_state], outputs=reset_outputs)
    use_calculator.change(reset_conversation, inputs=[agent_state], outputs=reset_outputs)


if __name__ == "__main__":
    demo.launch()
