import pytest

from agents.builder import build_agent, default_subagent_builder
from agents.plan_execute_agent import PlanExecuteAgent
from agents.react_agent import ReActAgent
from agents.reflection_agent import ReflectionAgent
from agents.toolcall_agent import ToolCallingAgent
from core.model import ModelClient


@pytest.fixture
def model_client() -> ModelClient:
    return ModelClient(provider="mock")


@pytest.mark.parametrize(
    "agent_type,expected_cls",
    [
        ("toolcall", ToolCallingAgent),
        ("react", ReActAgent),
        ("reflection", ReflectionAgent),
        ("plan_execute", PlanExecuteAgent),
        ("PLAN_EXECUTE", PlanExecuteAgent),
    ],
)
def test_build_agent_constructs_the_right_class(model_client, agent_type, expected_cls):
    agent = build_agent(agent_type, "bot", model_client)
    assert isinstance(agent, expected_cls)
    assert agent.name == "bot"


def test_build_agent_rejects_an_unknown_type(model_client):
    with pytest.raises(ValueError, match="Unsupported agent_type"):
        build_agent("nonexistent", "bot", model_client)


def test_build_agent_passes_through_tool_registry_and_extra_kwargs(model_client, echo_tool_registry):
    agent = build_agent("react", "bot", model_client, tool_registry=echo_tool_registry, max_steps=9)
    assert agent.tool_registry is echo_tool_registry
    assert agent.max_steps == 9


def test_default_subagent_builder_names_and_prompts_the_agent(model_client):
    agent = default_subagent_builder("reflection", model_client)
    assert agent.name == "subagent-reflection"
    assert "quality-focused" in agent.system_prompt


def test_build_agent_appends_system_prompt_suffix_after_the_default_prompt(model_client):
    agent = build_agent("react", "bot", model_client, system_prompt_suffix="<available_skills>...</available_skills>")

    assert agent.system_prompt.endswith("<available_skills>...</available_skills>")
    assert "finish" in agent.system_prompt  # ReAct 自带的 finish 工具约定不能被顶掉


def test_build_agent_appends_the_suffix_to_the_plan_execute_runner_prompt_too(model_client):
    agent = build_agent("plan_execute", "bot", model_client, system_prompt_suffix="SKILLS HERE")

    assert agent.system_prompt.endswith("SKILLS HERE")
    assert isinstance(agent, PlanExecuteAgent)
    assert agent.runner_system_prompt.endswith("SKILLS HERE")


def test_build_agent_without_a_suffix_leaves_prompts_untouched(model_client):
    agent = build_agent("plan_execute", "bot", model_client)

    assert "SKILLS HERE" not in agent.system_prompt
    assert agent.runner_system_prompt  # runner prompt 仍然存在
