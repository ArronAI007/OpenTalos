"""具名 provider 注册表：对齐 pi `packages/ai` 的 Provider Factories + 自动密钥环境变量解析，
但范围收窄到本仓库实际会用到的几个具名 provider（见 specs/004-model-provider-registry）。

一个具名 provider 只是"连接配置的预设"——不管是官方 API 还是任意 OpenAI 兼容服务商，实际的请
求/响应解析逻辑都复用 model.py 已有的三个后端类（ClaudeBackend/OpenAICompatibleBackend/
FakeModelBackend），这里只决定"用哪个默认 base_url、密钥读哪个环境变量、要不要声明式的请求参
数怪癖"。
"""
from dataclasses import dataclass
from typing import Literal

from .errors import SettingsError


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    default_base_url: str | None
    api_key_env_var: str | None
    supports_stream_usage: bool | None
    backend: Literal["anthropic", "openai-compatible", "mock"]
    # None 时请求体用现状字面量 "reasoning_effort"；非 None 时用这个名字承载推理强度参数。
    # 首批 provider 全部留空——没有证据表明需要和 OpenAI 原生命名不同的字段名（见 research.md
    # 决策 7），这个字段存在是为了让这个能力真正接入请求构造路径，供将来某个 provider 行使。
    reasoning_param_name: str | None = None


_REGISTRY: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        name="anthropic",
        default_base_url=None,  # 用 Anthropic SDK 自己的默认端点，和现状行为一致
        api_key_env_var="ANTHROPIC_API_KEY",
        supports_stream_usage=None,
        backend="anthropic",
    ),
    "openai": ProviderPreset(
        name="openai",
        default_base_url=None,  # 用 OpenAI SDK 自己的默认端点（https://api.openai.com/v1）
        api_key_env_var="OPENAI_API_KEY",
        supports_stream_usage=None,
        backend="openai-compatible",
    ),
    "deepseek": ProviderPreset(
        name="deepseek",
        default_base_url="https://api.deepseek.com",
        api_key_env_var="DEEPSEEK_API_KEY",
        supports_stream_usage=None,
        backend="openai-compatible",
    ),
    "moonshot": ProviderPreset(
        name="moonshot",
        default_base_url="https://api.moonshot.cn/v1",
        api_key_env_var="MOONSHOT_API_KEY",
        supports_stream_usage=None,
        backend="openai-compatible",
    ),
    "openai-compatible": ProviderPreset(
        name="openai-compatible",
        default_base_url=None,  # 现状行为：调用方必须自己提供 MODEL_BASE_URL
        api_key_env_var=None,  # 现状行为：没有专属变量，走通用 MODEL_API_KEY
        supports_stream_usage=None,
        backend="openai-compatible",
    ),
    "mock": ProviderPreset(
        name="mock",
        default_base_url=None,
        api_key_env_var=None,
        supports_stream_usage=None,
        backend="mock",
    ),
}


def get_provider_preset(name: str) -> ProviderPreset:
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY))
        raise SettingsError(f'Unknown MODEL_PROVIDER "{name}". Supported: {available}.') from None
