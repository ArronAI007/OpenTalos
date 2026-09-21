from core.settings import RuntimeSettings


def test_runtime_settings_has_expected_defaults():
    settings = RuntimeSettings()
    assert settings.temperature == 0.7
    assert settings.max_tokens is None
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.callback_timeout_seconds == 5.0


def test_runtime_settings_accepts_overrides():
    settings = RuntimeSettings(
        temperature=0.2, max_tokens=100, debug=True, log_level="DEBUG", callback_timeout_seconds=1.0
    )
    assert settings.temperature == 0.2
    assert settings.max_tokens == 100
    assert settings.debug is True
    assert settings.log_level == "DEBUG"
    assert settings.callback_timeout_seconds == 1.0
