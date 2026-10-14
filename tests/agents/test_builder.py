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
    # ReAct 自带的默认提示词（工具调用/不可信内容约定）不能被顶掉——finish 工具机制已移除
    # （见 002-pi-agent-core-alignment 的 finishTurn 替代），不再用"finish"关键字断言。
    assert "untrusted" in agent.system_prompt
