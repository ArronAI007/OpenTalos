from core.chat_message import ChatMessage
from context.tokens import TokenBudget


def test_estimate_text_returns_a_positive_count_for_nonempty_text():
    budget = TokenBudget()
    assert budget.estimate_text("hello world") > 0


def test_estimate_text_is_zero_for_empty_text():
    budget = TokenBudget()
    assert budget.estimate_text("") == 0


def test_estimate_message_caches_by_role_and_content():
    budget = TokenBudget()
    message = ChatMessage(content="hello world", role="user")

    first = budget.estimate_message(message)
    assert budget.cache_size == 1

    second = budget.estimate_message(message)
    assert second == first
    assert budget.cache_size == 1


def test_estimate_message_adds_role_overhead_on_top_of_text_tokens():
    budget = TokenBudget()
    message = ChatMessage(content="hello world", role="user")
    assert budget.estimate_message(message) == budget.estimate_text("hello world") + 4


def test_estimate_messages_sums_each_message():
    budget = TokenBudget()
    messages = [
        ChatMessage(content="hi", role="user"),
        ChatMessage(content="hello there", role="assistant"),
    ]
    total = budget.estimate_messages(messages)
    assert total == sum(budget.estimate_message(m) for m in messages)


def test_reset_cache_clears_cached_entries():
    budget = TokenBudget()
    budget.estimate_message(ChatMessage(content="hi", role="user"))
    assert budget.cache_size == 1

    budget.reset_cache()
    assert budget.cache_size == 0


def test_cache_stats_reports_message_count_and_total_tokens():
    budget = TokenBudget()
    budget.estimate_message(ChatMessage(content="hi", role="user"))
    budget.estimate_message(ChatMessage(content="hello there", role="assistant"))

    stats = budget.cache_stats()
    assert stats["cached_messages"] == 2
    assert stats["total_cached_tokens"] == sum(budget._cache.values())


def test_falls_back_to_character_estimate_when_encoding_unavailable():
    budget = TokenBudget()
    budget._encoding = None
    assert budget.estimate_text("12345678") == 2
