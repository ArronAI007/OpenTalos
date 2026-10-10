import pytest

from core.errors import (
    AgentRuntimeError,
    CoreError,
    EmptyModelResponse,
    ModelError,
    OperationCancelled,
    OutputLimitError,
    SettingsError,
)


@pytest.mark.parametrize(
    "exc_cls",
    [SettingsError, ModelError, EmptyModelResponse, AgentRuntimeError, OperationCancelled, OutputLimitError],
)
def test_errors_are_subclasses_of_core_error(exc_cls):
    assert issubclass(exc_cls, CoreError)


def test_operation_cancelled_and_output_limit_are_agent_runtime_errors():
    assert issubclass(OperationCancelled, AgentRuntimeError)
    assert issubclass(OutputLimitError, AgentRuntimeError)


def test_empty_model_response_is_a_model_error():
    assert issubclass(EmptyModelResponse, ModelError)


def test_core_error_is_a_plain_exception():
    assert issubclass(CoreError, Exception)
