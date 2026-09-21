from core.completion import Completion
from agents.reflection_agent import SATISFIED_MARKER, ReflectionAgent


async def test_arespond_stops_early_when_critique_is_satisfied(scripted_client):
    client = scripted_client(
        completions=[
            Completion(text="first draft", model_id="mock"),
            Completion(text=SATISFIED_MARKER, model_id="mock"),
        ]
    )
    agent = ReflectionAgent(name="bot", model_client=client, max_rounds=3)

    answer = await agent.arespond("write a haiku")

    assert answer == "first draft"
    assert [entry["phase"] for entry in agent.trace] == ["draft", "critique"]


async def test_arespond_revises_until_satisfied_or_out_of_rounds(scripted_client):
    client = scripted_client(
        completions=[
            Completion(text="draft v1", model_id="mock"),
            Completion(text="needs more detail", model_id="mock"),
            Completion(text="draft v2", model_id="mock"),
            Completion(text=SATISFIED_MARKER, model_id="mock"),
        ]
    )
    agent = ReflectionAgent(name="bot", model_client=client, max_rounds=3)

    answer = await agent.arespond("write a summary")

    assert answer == "draft v2"
    assert [entry["phase"] for entry in agent.trace] == ["draft", "critique", "draft", "critique"]


async def test_arespond_gives_up_after_max_rounds_without_satisfaction(scripted_client):
    # Each unsatisfied critique triggers one more revise, including on the last round, so
    # max_rounds=2 consumes: draft, critique, revise, critique, revise (5 calls).
    client = scripted_client(
        completions=[
            Completion(text="draft v1", model_id="mock"),
            Completion(text="still needs work", model_id="mock"),
            Completion(text="draft v2", model_id="mock"),
            Completion(text="still needs work", model_id="mock"),
            Completion(text="draft v3", model_id="mock"),
        ]
    )
    agent = ReflectionAgent(name="bot", model_client=client, max_rounds=2)

    answer = await agent.arespond("write a summary")

    assert answer == "draft v3"
    assert [entry["phase"] for entry in agent.trace] == ["draft", "critique", "draft", "critique", "draft"]
