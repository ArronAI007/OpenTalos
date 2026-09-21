import pytest

from core.exceptions import ConfigError
from core.llm_adapters import MockAdapter, create_adapter
from core.llm_response import LLMResponse


async def test_mock_adapter_ainvoke_returns_configured_response():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi there", model="mock-model"))
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == "hi there"


async def test_mock_adapter_ainvoke_uses_responder_when_given():
    def responder(messages):
        return LLMResponse(content=f"echo: {messages[-1]['content']}", model="mock-model")

    adapter = MockAdapter(model="mock-model", responder=responder)
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == "echo: hello"


async def test_mock_adapter_ainvoke_defaults_to_empty_content_when_unconfigured():
    adapter = MockAdapter(model="mock-model")
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == ""


async def test_mock_adapter_astream_invoke_yields_response_content_character_by_character():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="ab", model="mock-model"))
    chunks = [chunk async for chunk in adapter.astream_invoke([{"role": "user", "content": "hi"}])]
    assert chunks == ["a", "b"]
    assert adapter.last_stats is not None


async def test_mock_adapter_ainvoke_with_tools_returns_no_tool_calls():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi", model="mock-model"))
    result = await adapter.ainvoke_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert result.tool_calls == []
    assert result.content == "hi"


def test_create_adapter_returns_mock_adapter_for_mock_provider():
    adapter = create_adapter("mock", api_key="mock", base_url=None, timeout=60, model="mock-model")
    assert isinstance(adapter, MockAdapter)


def test_create_adapter_rejects_unknown_provider():
    with pytest.raises(ConfigError, match="Unknown MODEL_PROVIDER"):
        create_adapter("does-not-exist", api_key="k", base_url=None, timeout=60, model="m")
