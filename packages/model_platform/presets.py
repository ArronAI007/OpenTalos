"""Built-in provider connection presets for the model control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    backend: str
    default_base_url: str | None
    api_key_label: str = "API key"
    supports_model_discovery: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_PRESETS = (
    ProviderPreset("anthropic", "Anthropic", "anthropic", None),
    ProviderPreset("openai", "OpenAI", "openai-compatible", "https://api.openai.com/v1"),
    ProviderPreset(
        "google-gemini",
        "Google Gemini",
        "openai-compatible",
        "https://generativelanguage.googleapis.com/v1beta/openai",
    ),
    ProviderPreset(
        "google-gemini-native",
        "Google Gemini Native",
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
    ),
    ProviderPreset(
        "openai-responses",
        "OpenAI Responses",
        "openai-responses",
        "https://api.openai.com/v1",
    ),
    ProviderPreset("deepseek", "DeepSeek", "openai-compatible", "https://api.deepseek.com"),
    ProviderPreset("moonshot", "Kimi / Moonshot", "openai-compatible", "https://api.moonshot.cn/v1"),
    ProviderPreset("zhipu", "Zhipu GLM", "openai-compatible", "https://open.bigmodel.cn/api/paas/v4"),
    ProviderPreset("minimax", "MiniMax", "openai-compatible", "https://api.minimax.chat/v1"),
    ProviderPreset("stepfun", "StepFun", "openai-compatible", "https://api.stepfun.com/v1"),
    ProviderPreset("qwen", "Qwen", "openai-compatible", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ProviderPreset("mistral", "Mistral", "openai-compatible", "https://api.mistral.ai/v1"),
    ProviderPreset("groq", "Groq", "openai-compatible", "https://api.groq.com/openai/v1"),
    ProviderPreset("xai", "xAI", "openai-compatible", "https://api.x.ai/v1"),
    ProviderPreset("openrouter", "OpenRouter", "openai-compatible", "https://openrouter.ai/api/v1"),
    ProviderPreset("together", "Together AI", "openai-compatible", "https://api.together.xyz/v1"),
    ProviderPreset("siliconflow", "SiliconFlow", "openai-compatible", "https://api.siliconflow.cn/v1"),
    ProviderPreset("ollama", "Ollama", "openai-compatible", "http://127.0.0.1:11434/v1"),
    ProviderPreset("lmstudio", "LM Studio", "openai-compatible", "http://127.0.0.1:1234/v1"),
    ProviderPreset("openai-compatible", "OpenAI-compatible", "openai-compatible", None),
    ProviderPreset("anthropic-compatible", "Anthropic-compatible", "anthropic", None),
    ProviderPreset("mock", "Mock", "mock", None, supports_model_discovery=False),
)

_BY_ID = {preset.id: preset for preset in _PRESETS}


def list_presets() -> list[ProviderPreset]:
    return list(_PRESETS)


def get_preset(provider_id: str) -> ProviderPreset | None:
    return _BY_ID.get(provider_id)
