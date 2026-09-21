import pytest

from agents.builder import build_agent, default_subagent_builder
from agents.critique_agent import CritiqueAgent
from agents.planner_agent import PlannerAgent
from agents.stepwise_agent import StepwiseAgent
from agents.toolcall_agent import ToolCallingAgent
from core.model_client import ModelClient


@pytest.fixture
def model_client() -> ModelClient:
    return ModelClient(provider="mock")


@pytest.mark.parametrize(
    "agent_type,expected_cls",
    [
        ("toolcall", ToolCallingAgent),
        ("stepwise", StepwiseAgent),
        ("critique", CritiqueAgent),
        ("planner", PlannerAgent),
        ("PLANNER", PlannerAgent),
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
    agent = build_agent("stepwise", "bot", model_client, tool_registry=echo_tool_registry, max_steps=9)
    assert agent.tool_registry is echo_tool_registry
    assert agent.max_steps == 9


def test_default_subagent_builder_names_and_prompts_the_agent(model_client):
    agent = default_subagent_builder("critique", model_client)
    assert agent.name == "subagent-critique"
    assert "quality-focused" in agent.system_prompt
