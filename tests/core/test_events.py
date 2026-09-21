from core.events import AgentPhase, PhaseSignal


def test_phase_signal_emit_sets_timestamp_and_data():
    signal = PhaseSignal.emit(AgentPhase.STARTED, "my-agent", input_text="hi")
    assert signal.phase == AgentPhase.STARTED
    assert signal.agent_name == "my-agent"
    assert signal.data == {"input_text": "hi"}
    assert signal.timestamp > 0


def test_phase_signal_to_dict_uses_phase_value():
    signal = PhaseSignal.emit(AgentPhase.FINISHED, "my-agent", result="done")
    data = signal.to_dict()
    assert data == {
        "phase": "finished",
        "timestamp": signal.timestamp,
        "agent_name": "my-agent",
        "data": {"result": "done"},
    }
