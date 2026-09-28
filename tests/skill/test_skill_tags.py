from pathlib import Path

from skill.skill_tags import get_tags, load_tags


def test_load_tags_returns_empty_dict_when_file_is_missing(tmp_path: Path):
    store_path = tmp_path / "skill_tags.json"

    assert load_tags(store_path) == {}


def test_load_tags_reads_an_existing_file(tmp_path: Path):
    store_path = tmp_path / "skill_tags.json"
    store_path.write_text('{"date": ["编程"]}', encoding="utf-8")

    assert load_tags(store_path) == {"date": ["编程"]}


def test_get_tags_returns_empty_list_for_an_unknown_skill(tmp_path: Path):
    store_path = tmp_path / "skill_tags.json"
    store_path.write_text('{"date": ["编程"]}', encoding="utf-8")

    assert get_tags(store_path, "does-not-exist") == []


def test_get_tags_returns_the_skills_tags(tmp_path: Path):
    store_path = tmp_path / "skill_tags.json"
    store_path.write_text('{"date": ["编程"], "csv-to-json": ["数据", "编程"]}', encoding="utf-8")

    assert get_tags(store_path, "csv-to-json") == ["数据", "编程"]
