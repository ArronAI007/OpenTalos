from core.config import Config


def test_config_has_expected_defaults():
    config = Config()
    assert config.temperature == 0.7
    assert config.max_tokens is None
    assert config.debug is False
    assert config.log_level == "INFO"
    assert config.hook_timeout_seconds == 5.0


def test_config_accepts_overrides():
    config = Config(temperature=0.2, max_tokens=100, debug=True, log_level="DEBUG", hook_timeout_seconds=1.0)
    assert config.temperature == 0.2
    assert config.max_tokens == 100
    assert config.debug is True
    assert config.log_level == "DEBUG"
    assert config.hook_timeout_seconds == 1.0
