def test_core_package_exports_public_api():
    import core

    expected = {
        "Agent",
        "Config",
        "OpenTalosError",
        "ConfigError",
        "LLMError",
        "AgentError",
        "AgentEvent",
        "EventType",
        "LifecycleHook",
        "LLMClient",
        "Completion",
        "ToolCompletion",
        "StreamSummary",
        "ToolInvocation",
        "Message",
        "MessageRole",
    }
    assert expected.issubset(set(core.__all__))
    for name in expected:
        assert hasattr(core, name)
