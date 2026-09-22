from core.agent import Agent, RuntimeSettings
from core.model import ModelClient
from tool.registry import ToolRegistry

from .plan_execute_agent import PlanExecuteAgent
from .react_agent import ReActAgent
from .reflection_agent import ReflectionAgent
from .toolcall_agent import ToolCallingAgent

AGENT_TYPES: dict[str, type[Agent]] = {
    "toolcall": ToolCallingAgent,
    "react": ReActAgent,
    "reflection": ReflectionAgent,
    "plan_execute": PlanExecuteAgent,
}


def build_agent(
    agent_type: str,
    name: str,
    model_client: ModelClient,
    *,
    tool_registry: ToolRegistry | None = None,
    settings: RuntimeSettings | None = None,
    system_prompt: str | None = None,
    system_prompt_suffix: str | None = None,
    **kwargs: object,
) -> Agent:
    key = agent_type.lower()
    agent_cls = AGENT_TYPES.get(key)
    if agent_cls is None:
        raise ValueError(f'Unsupported agent_type "{agent_type}". Supported: {", ".join(AGENT_TYPES)}.')
    agent = agent_cls(
        name=name,
        model_client=model_client,
        tool_registry=tool_registry,
        settings=settings,
        system_prompt=system_prompt,
        **kwargs,
    )
    if system_prompt_suffix:
        # 追加（而不是替换）是为了保住各类型的默认提示词——比如 ReAct 的 finish 工具约定。
        # PlanExecuteAgent 的执行阶段用独立的 runner prompt，同样需要知道能力清单。
        agent.system_prompt = _append_suffix(agent.system_prompt, system_prompt_suffix)
        if isinstance(agent, PlanExecuteAgent):
            agent.runner_system_prompt = _append_suffix(agent.runner_system_prompt, system_prompt_suffix)
    return agent


def _append_suffix(prompt: str | None, suffix: str) -> str:
    return f"{prompt}\n\n{suffix}" if prompt else suffix


SUBAGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "toolcall": "You are a focused sub-agent. Complete the delegated sub-task directly and concisely.",
    "react": "You are a focused sub-agent. Use tools efficiently and finish within the step budget.",
    "reflection": "You are a quality-focused sub-agent. Draft, critique, and refine your answer before returning it.",
    "plan_execute": "You are a planning sub-agent. Break the delegated task into steps and execute them in order.",
}


def default_subagent_builder(
    agent_type: str,
    model_client: ModelClient,
    *,
    tool_registry: ToolRegistry | None = None,
    settings: RuntimeSettings | None = None,
) -> Agent:
    """框架自带的子代理构造函数，调用方可以传自己的实现替换掉。"""
    key = agent_type.lower()
    return build_agent(
        key,
        name=f"subagent-{key}",
        model_client=model_client,
        tool_registry=tool_registry,
        settings=settings,
        system_prompt=SUBAGENT_SYSTEM_PROMPTS.get(key, SUBAGENT_SYSTEM_PROMPTS["toolcall"]),
    )
