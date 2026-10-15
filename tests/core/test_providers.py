"""具名 provider 注册表的单测：纯数据查询，不涉及网络/SDK。"""
import pytest

from core.errors import SettingsError
from core.providers import get_provider_preset


class TestGetProviderPreset:
    def test_unknown_provider_raises_and_lists_available_names(self) -> None:
        with pytest.raises(SettingsError) as exc_info:
            get_provider_preset("no-such-provider")
        message = str(exc_info.value)
        assert "no-such-provider" in message
        for name in ("anthropic", "openai", "deepseek", "moonshot", "openai-compatible", "mock"):
            assert name in message

    def test_anthropic_preset_matches_current_behavior(self) -> None:
        preset = get_provider_preset("anthropic")
        assert preset.default_base_url is None
        assert preset.api_key_env_var == "ANTHROPIC_API_KEY"
        assert preset.backend == "anthropic"
        assert preset.supports_stream_usage is None
        assert preset.reasoning_param_name is None

    def test_openai_compatible_preset_matches_current_behavior(self) -> None:
        preset = get_provider_preset("openai-compatible")
        assert preset.default_base_url is None
        assert preset.api_key_env_var is None
        assert preset.backend == "openai-compatible"
        assert preset.supports_stream_usage is None

    def test_mock_preset_matches_current_behavior(self) -> None:
        preset = get_provider_preset("mock")
        assert preset.default_base_url is None
        assert preset.api_key_env_var is None
        assert preset.backend == "mock"

    def test_openai_preset(self) -> None:
        preset = get_provider_preset("openai")
        assert preset.api_key_env_var == "OPENAI_API_KEY"
        assert preset.backend == "openai-compatible"

    def test_deepseek_preset(self) -> None:
        preset = get_provider_preset("deepseek")
        assert preset.default_base_url == "https://api.deepseek.com"
        assert preset.api_key_env_var == "DEEPSEEK_API_KEY"
        assert preset.backend == "openai-compatible"

    def test_moonshot_preset(self) -> None:
        preset = get_provider_preset("moonshot")
        assert preset.default_base_url == "https://api.moonshot.cn/v1"
        assert preset.api_key_env_var == "MOONSHOT_API_KEY"
        assert preset.backend == "openai-compatible"
