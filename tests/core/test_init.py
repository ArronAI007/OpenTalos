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
        "LLMResponse",
        "LLMToolResponse",
        "StreamStats",
        "ToolCall",
        "Message",
        "MessageRole",
    }
    assert expected.issubset(set(core.__all__))
    for name in expected:
        assert hasattr(core, name)
