from tool.circuit_breaker import CircuitBreaker


def test_allow_is_true_for_a_tool_with_no_recorded_failures():
    breaker = CircuitBreaker()
    assert breaker.allow("search") is True


def test_allow_becomes_false_after_reaching_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record("search", success=False)
    assert breaker.allow("search") is True
    breaker.record("search", success=False)
    assert breaker.allow("search") is False


def test_a_success_resets_the_failure_count():
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record("search", success=False)
    breaker.record("search", success=True)
    breaker.record("search", success=False)
    assert breaker.allow("search") is True


def test_allow_recovers_after_recovery_seconds_have_elapsed(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr("tool.circuit_breaker.time.monotonic", lambda: fake_now[0])

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    breaker.record("search", success=False)
    assert breaker.allow("search") is False

    fake_now[0] += 60
    assert breaker.allow("search") is True


def test_failure_count_resets_after_recovery(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr("tool.circuit_breaker.time.monotonic", lambda: fake_now[0])

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    breaker.record("search", success=False)
    fake_now[0] += 60
    assert breaker.allow("search") is True
    breaker.record("search", success=False)
    assert breaker.allow("search") is False
