from agents.builder import build_agent
from agents.react_agent import ReActAgent
from core.model import ModelClient


def test_build_agent_constructs_a_react_agent():
    client = ModelClient(provider="mock")
    agent = build_agent("bot", client)
    assert isinstance(agent, ReActAgent)
    assert agent.name == "bot"


def test_build_agent_passes_through_tool_registry_and_extra_kwargs(echo_tool_registry):
    client = ModelClient(provider="mock")
    agent = build_agent("bot", client, tool_registry=echo_tool_registry, max_steps=9)
    assert agent.tool_registry is echo_tool_registry
    assert agent.max_steps == 9


def test_build_agent_appends_system_prompt_suffix_after_the_default_prompt():
    client = ModelClient(provider="mock")
    agent = build_agent("bot", client, system_prompt_suffix="<available_skills>...</available_skills>")

    assert agent.system_prompt.endswith("<available_skills>...</available_skills>")
    assert "finish" in agent.system_prompt  # ReAct 自带的 finish 工具约定不能被顶掉
