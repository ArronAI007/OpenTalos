import pytest

from core.exceptions import AgentError, ConfigError, LLMError, OpenTalosError


@pytest.mark.parametrize("exc_cls", [ConfigError, LLMError, AgentError])
def test_exceptions_are_subclasses_of_opentalos_error(exc_cls):
    assert issubclass(exc_cls, OpenTalosError)


def test_opentalos_error_is_a_plain_exception():
    assert issubclass(OpenTalosError, Exception)
