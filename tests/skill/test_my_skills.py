from pathlib import Path

from skill.my_skills import add_my_skill, load_my_skills, remove_my_skill, save_my_skills


def test_load_my_skills_seeds_from_all_skill_names_when_file_is_missing(tmp_path: Path):
    store_path = tmp_path / "my_skills.json"

    names = load_my_skills(store_path, ["date", "csv-to-json"])

    assert names == {"date", "csv-to-json"}
    assert store_path.is_file()  # 首次访问就写盘，不是只在内存里


def test_load_my_skills_reads_back_an_existing_file_without_reseeding(tmp_path: Path):
    store_path = tmp_path / "my_skills.json"
    save_my_skills(store_path, {"date"})

    # all_skill_names 现在包含一个新技能，但已有文件不应该被新技能名污染。
    names = load_my_skills(store_path, ["date", "csv-to-json"])

    assert names == {"date"}


def test_add_my_skill_returns_false_for_an_unknown_name(tmp_path: Path):
    store_path = tmp_path / "my_skills.json"

    added = add_my_skill(store_path, ["date"], "does-not-exist")

    assert added is False


def test_add_my_skill_persists_the_addition(tmp_path: Path):
    store_path = tmp_path / "my_skills.json"
    save_my_skills(store_path, set())

    added = add_my_skill(store_path, ["date", "csv-to-json"], "csv-to-json")

    assert added is True
    assert load_my_skills(store_path, ["date", "csv-to-json"]) == {"csv-to-json"}


def test_remove_my_skill_is_idempotent(tmp_path: Path):
    store_path = tmp_path / "my_skills.json"
    save_my_skills(store_path, {"date"})

    remove_my_skill(store_path, ["date"], "date")
    remove_my_skill(store_path, ["date"], "date")  # 第二次调用不应该报错

    assert load_my_skills(store_path, ["date"]) == set()
