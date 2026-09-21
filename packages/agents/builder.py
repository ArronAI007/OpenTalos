from core.agent import Agent
from core.model_client import ModelClient
from core.settings import RuntimeSettings
from tool.registry import ToolRegistry

from .critique_agent import CritiqueAgent
from .planner_agent import PlannerAgent
from .stepwise_agent import StepwiseAgent
from .toolcall_agent import ToolCallingAgent

AGENT_TYPES: dict[str, type[Agent]] = {
    "toolcall": ToolCallingAgent,
    "stepwise": StepwiseAgent,
    "critique": CritiqueAgent,
    "planner": PlannerAgent,
}


def build_agent(
    agent_type: str,
    name: str,
    model_client: ModelClient,
    *,
    tool_registry: ToolRegistry | None = None,
    settings: RuntimeSettings | None = None,
    system_prompt: str | None = None,
    **kwargs: object,
) -> Agent:
    key = agent_type.lower()
    agent_cls = AGENT_TYPES.get(key)
    if agent_cls is None:
        raise ValueError(f'Unsupported agent_type "{agent_type}". Supported: {", ".join(AGENT_TYPES)}.')
    return agent_cls(
        name=name,
        model_client=model_client,
        tool_registry=tool_registry,
        settings=settings,
        system_prompt=system_prompt,
        **kwargs,
    )


SUBAGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "toolcall": "You are a focused sub-agent. Complete the delegated sub-task directly and concisely.",
    "stepwise": "You are a focused sub-agent. Use tools efficiently and finish within the step budget.",
    "critique": "You are a quality-focused sub-agent. Draft, critique, and refine your answer before returning it.",
    "planner": "You are a planning sub-agent. Break the delegated task into steps and execute them in order.",
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
