def test_tool_package_exports_public_api():
    import tool

    expected = {
        "Tool",
        "ToolParameter",
        "ToolOutcome",
        "OutcomeStatus",
        "FailureCode",
        "ToolRegistry",
        "CircuitBreaker",
    }
    assert expected.issubset(set(tool.__all__))
    for name in expected:
        assert hasattr(tool, name)
