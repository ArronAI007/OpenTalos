import pytest

from core.errors import AgentRuntimeError, CoreError, ModelError, SettingsError


@pytest.mark.parametrize("exc_cls", [SettingsError, ModelError, AgentRuntimeError])
def test_errors_are_subclasses_of_core_error(exc_cls):
    assert issubclass(exc_cls, CoreError)


def test_core_error_is_a_plain_exception():
    assert issubclass(CoreError, Exception)
