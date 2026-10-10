from core.agent import Agent, RuntimeSettings
from core.model import ModelClient
from tool.registry import ToolRegistry

from .react_agent import ReActAgent


def build_agent(
    name: str,
    model_client: ModelClient,
    *,
    tool_registry: ToolRegistry | None = None,
    settings: RuntimeSettings | None = None,
    system_prompt: str | None = None,
    system_prompt_suffix: str | None = None,
    **kwargs: object,
) -> Agent:
    agent = ReActAgent(
        name=name,
        model_client=model_client,
        tool_registry=tool_registry,
        settings=settings,
        system_prompt=system_prompt,
        **kwargs,
    )
    if system_prompt_suffix:
        # 追加（而不是替换）是为了保住 ReAct 的 finish 工具约定这条默认提示词。
        agent.system_prompt = _append_suffix(agent.system_prompt, system_prompt_suffix)
    return agent


def _append_suffix(prompt: str | None, suffix: str) -> str:
    return f"{prompt}\n\n{suffix}" if prompt else suffix
