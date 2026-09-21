from core.lifecycle import AgentEvent, EventType


def test_agent_event_create_sets_timestamp_and_data():
    event = AgentEvent.create(EventType.AGENT_START, "my-agent", input_text="hi")
    assert event.type == EventType.AGENT_START
    assert event.agent_name == "my-agent"
    assert event.data == {"input_text": "hi"}
    assert event.timestamp > 0


def test_agent_event_to_dict_uses_event_type_value():
    event = AgentEvent.create(EventType.AGENT_FINISH, "my-agent", result="done")
    data = event.to_dict()
    assert data == {
        "type": "agent_finish",
        "timestamp": event.timestamp,
        "agent_name": "my-agent",
        "data": {"result": "done"},
    }
