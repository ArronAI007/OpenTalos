from tool.outcome import FailureCode, OutcomeStatus, ToolOutcome


def test_ok_factory_sets_status_and_output():
    outcome = ToolOutcome.ok("42")
    assert outcome.status == OutcomeStatus.OK
    assert outcome.output == "42"
    assert outcome.failure_code is None
    assert outcome.succeeded is True


def test_error_factory_defaults_to_execution_failed_code():
    outcome = ToolOutcome.error("boom")
    assert outcome.status == OutcomeStatus.ERROR
    assert outcome.output == "boom"
    assert outcome.failure_code == FailureCode.EXECUTION_FAILED
    assert outcome.succeeded is False


def test_error_factory_accepts_explicit_code():
    outcome = ToolOutcome.error("missing arg", code=FailureCode.INVALID_ARGUMENTS)
    assert outcome.failure_code == FailureCode.INVALID_ARGUMENTS


def test_duration_ms_defaults_to_zero_and_can_be_set():
    outcome = ToolOutcome.ok("42", duration_ms=15)
    assert outcome.duration_ms == 15
