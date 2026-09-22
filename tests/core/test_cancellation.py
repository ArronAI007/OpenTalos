import asyncio

import pytest

from core.cancellation import CancellationToken
from core.errors import OperationCancelled


def test_is_cancelled_is_false_by_default():
    token = CancellationToken()
    assert token.is_cancelled is False


def test_cancel_sets_is_cancelled():
    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True


def test_raise_if_cancelled_is_a_noop_when_not_cancelled():
    token = CancellationToken()
    token.raise_if_cancelled()  # should not raise


def test_raise_if_cancelled_raises_after_cancel():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()


def test_token_budget_is_not_exceeded_below_the_limit():
    token = CancellationToken(token_budget=100)
    token.record_tokens(60)
    assert token.is_cancelled is False


def test_token_budget_is_exceeded_once_recorded_usage_reaches_the_limit():
    token = CancellationToken(token_budget=100)
    token.record_tokens(60)
    token.record_tokens(40)
    assert token.is_cancelled is True


def test_raise_if_cancelled_reports_the_token_budget_in_the_message():
    token = CancellationToken(token_budget=100)
    token.record_tokens(100)
    with pytest.raises(OperationCancelled, match="100 tokens"):
        token.raise_if_cancelled()


def test_no_token_budget_means_unlimited_usage():
    token = CancellationToken()
    token.record_tokens(1_000_000)
    assert token.is_cancelled is False


async def test_timeout_seconds_is_not_exceeded_immediately():
    token = CancellationToken(timeout_seconds=10)
    assert token.is_cancelled is False


async def test_timeout_seconds_is_exceeded_after_it_elapses():
    token = CancellationToken(timeout_seconds=0.01)
    await asyncio.sleep(0.02)
    assert token.is_cancelled is True


async def test_raise_if_cancelled_reports_the_timeout():
    token = CancellationToken(timeout_seconds=0.01)
    await asyncio.sleep(0.02)
    with pytest.raises(OperationCancelled, match="timeout"):
        token.raise_if_cancelled()
