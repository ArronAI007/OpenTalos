import pytest

from dataset import DEMO_PROBLEMS, load_problems


def test_demo_problems_has_at_least_40_entries() -> None:
    assert len(DEMO_PROBLEMS) >= 40


def test_demo_problems_have_required_fields() -> None:
    for item in DEMO_PROBLEMS:
        assert item["question"]
        assert item["answer"]
        assert item["solution"]
        float(item["answer"])  # answer 必须是可解析成数字的字符串


def test_load_problems_returns_requested_count() -> None:
    assert len(load_problems(5)) == 5


def test_load_problems_is_deterministic() -> None:
    assert load_problems(10) == load_problems(10)


def test_load_problems_rejects_more_than_available() -> None:
    with pytest.raises(ValueError, match="only"):
        load_problems(len(DEMO_PROBLEMS) + 1)


def test_load_problems_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError, match="positive"):
        load_problems(0)
