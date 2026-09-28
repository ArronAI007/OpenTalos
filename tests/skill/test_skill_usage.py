from pathlib import Path

from skill.skill_usage import get_usage_count, increment_usage, load_usage


def test_load_usage_returns_empty_dict_when_file_is_missing(tmp_path: Path):
    store_path = tmp_path / "skill_usage.json"

    assert load_usage(store_path) == {}


def test_get_usage_count_defaults_to_zero_for_an_unknown_skill(tmp_path: Path):
    store_path = tmp_path / "skill_usage.json"

    assert get_usage_count(store_path, "date") == 0


def test_increment_usage_starts_at_one_and_persists(tmp_path: Path):
    store_path = tmp_path / "skill_usage.json"

    result = increment_usage(store_path, "date")

    assert result == 1
    assert get_usage_count(store_path, "date") == 1


def test_increment_usage_accumulates_across_calls(tmp_path: Path):
    store_path = tmp_path / "skill_usage.json"

    increment_usage(store_path, "date")
    increment_usage(store_path, "date")
    third = increment_usage(store_path, "date")

    assert third == 3
    assert get_usage_count(store_path, "date") == 3


def test_increment_usage_tracks_skills_independently(tmp_path: Path):
    store_path = tmp_path / "skill_usage.json"

    increment_usage(store_path, "date")
    increment_usage(store_path, "csv-to-json")
    increment_usage(store_path, "csv-to-json")

    assert get_usage_count(store_path, "date") == 1
    assert get_usage_count(store_path, "csv-to-json") == 2
