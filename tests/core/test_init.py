def test_core_package_exports_public_api():
    import core

    expected = {
        "Agent",
        "RuntimeSettings",
        "CoreError",
        "SettingsError",
        "ModelError",
        "EmptyModelResponse",
        "AgentRuntimeError",
        "OutputLimitError",
        "AgentEvent",
        "EventKind",
        "PhaseCallback",
        "Completion",
        "ToolCompletion",
        "StreamSummary",
        "ToolInvocation",
        "ChatMessage",
        "SpeakerRole",
    }
    assert expected.issubset(set(core.__all__))
    for name in expected:
        assert hasattr(core, name)
