import httpx

from providers.anthropic_provider import AnthropicProvider
from providers.mock_provider import MockProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_compatible_provider import OpenAICompatibleProvider


class FakeAnthropicContentBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeAnthropicResponse:
    def __init__(self, text: str) -> None:
        self.content = [FakeAnthropicContentBlock(text)]


class FakeAnthropicMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.captured_params: dict[str, object] | None = None

    async def create(self, **params: object) -> FakeAnthropicResponse:
        self.captured_params = params
        return FakeAnthropicResponse(self._text)


class FakeAnthropicClient:
    def __init__(self, text: str) -> None:
        self.messages = FakeAnthropicMessages(text)


async def test_anthropic_provider_returns_concatenated_text_blocks() -> None:
    client = FakeAnthropicClient("你好")
    provider = AnthropicProvider(client, model="claude-test")
    result = await provider.complete_text("system", "user")
    assert result == "你好"
    assert client.messages.captured_params["system"] == "system"
    assert client.messages.captured_params["messages"] == [{"role": "user", "content": "user"}]


class FakeOpenAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeOpenAIChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeOpenAIMessage(content)


class FakeOpenAIResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeOpenAIChoice(content)]


class FakeOpenAICompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.captured_params: dict[str, object] | None = None

    async def create(self, **params: object) -> FakeOpenAIResponse:
        self.captured_params = params
        return FakeOpenAIResponse(self._content)


class FakeOpenAIChat:
    def __init__(self, content: str) -> None:
        self.completions = FakeOpenAICompletions(content)


class FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        self.chat = FakeOpenAIChat(content)


async def test_openai_compatible_provider_returns_message_content() -> None:
    client = FakeOpenAIClient("你好")
    provider = OpenAICompatibleProvider(client, model="gpt-test")
    result = await provider.complete_text("system", "user")
    assert result == "你好"
    assert client.chat.completions.captured_params["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]


async def test_ollama_provider_posts_to_api_chat_and_returns_message_content() -> None:
    captured: dict[str, object] = {}

    async def fake_post(url: str, json_body: dict[str, object]) -> httpx.Response:
        captured["url"] = url
        captured["json_body"] = json_body
        return httpx.Response(200, json={"message": {"content": "你好"}}, request=httpx.Request("POST", url))

    provider = OllamaProvider(fake_post, base_url="http://localhost:11434", model="llama3")
    result = await provider.complete_text("system", "user")
    assert result == "你好"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json_body"]["stream"] is False


async def test_mock_provider_returns_a_nonempty_string() -> None:
    provider = MockProvider()
    result = await provider.complete_text("system", "user")
    assert isinstance(result, str)
    assert len(result) > 0
