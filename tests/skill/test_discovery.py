from pathlib import Path

from skill.discovery import discover_skills


def test_discover_skills_finds_all_skill_directories_with_a_skill_md(tmp_path: Path) -> None:
    skill_a = tmp_path / "alpha"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text("# alpha\n\nDoes alpha things.\n", encoding="utf-8")

    skill_b = tmp_path / "beta"
    skill_b.mkdir()
    (skill_b / "SKILL.md").write_text("# beta\n\nDoes beta things.\n", encoding="utf-8")

    not_a_skill = tmp_path / "not-a-skill"
    not_a_skill.mkdir()
    (not_a_skill / "README.md").write_text("not a skill", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert {s.name for s in skills} == {"alpha", "beta"}


def test_discover_skills_extracts_the_first_line_after_the_heading_as_description(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# alpha\n\nDoes alpha things.\n\nMore detail here.\n", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert skills[0].description == "Does alpha things."


def test_discover_skills_returns_the_full_skill_md_content(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    content = "# alpha\n\nDoes alpha things.\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert skills[0].content == content
    assert skills[0].dir == skill_dir


def test_discover_skills_returns_empty_list_for_a_nonexistent_directory(tmp_path: Path) -> None:
    assert discover_skills(tmp_path / "does-not-exist") == []
