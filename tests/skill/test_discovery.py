import os
from datetime import datetime
from pathlib import Path

from skill.discovery import discover_skills, list_skill_files


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


def test_discover_skills_prefers_frontmatter_description_when_present(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    content = "---\nname: alpha\ndescription: From frontmatter.\n---\n# alpha\n\nFrom heading instead.\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert skills[0].description == "From frontmatter."


def test_discover_skills_includes_updated_at_from_file_mtime(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# alpha\n\nDoes alpha things.\n", encoding="utf-8")
    fixed_timestamp = 1700000000
    os.utime(skill_md, (fixed_timestamp, fixed_timestamp))

    skills = discover_skills(tmp_path)

    expected = datetime.fromtimestamp(fixed_timestamp).strftime("%Y-%m-%dT%H:%M:%S")
    assert skills[0].updated_at == expected


def test_list_skill_files_returns_every_file_with_its_relative_path(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    files = list_skill_files(skill_dir)

    assert files == [
        ("SKILL.md", "# alpha\n"),
        ("scripts/main.py", "print('hi')\n"),
    ]


def test_list_skill_files_reports_none_content_for_undecodable_files(tmp_path: Path) -> None:
    skill_dir = tmp_path / "alpha"
    skill_dir.mkdir()
    (skill_dir / "image.png").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x00\x00\xff\xd9")

    files = list_skill_files(skill_dir)

    assert files == [("image.png", None)]
