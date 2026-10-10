from pathlib import Path

from skill.discovery import Skill
from skill.prompt import format_skills_for_system_prompt


def _skill(name: str, description: str, tmp_path: Path) -> Skill:
    return Skill(
        name=name,
        description=description,
        content="",
        dir=tmp_path / name,
        updated_at="2026-01-01T00:00:00",
    )


def test_empty_skill_list_renders_nothing() -> None:
    assert format_skills_for_system_prompt([]) == ""


def test_renders_names_descriptions_and_locations(tmp_path: Path) -> None:
    skills = [
        _skill("date", "计算相对于今天的日期。", tmp_path),
        _skill("csv-to-json", "Convert CSV text to JSON.", tmp_path),
    ]

    text = format_skills_for_system_prompt(skills)

    assert "<available_skills>" in text
    assert "</available_skills>" in text
    assert "<name>date</name>" in text
    assert "<description>计算相对于今天的日期。</description>" in text
    assert "<name>csv-to-json</name>" in text
    # pi 式方案：给出 SKILL.md 的绝对路径，模型用 read 工具打开它。
    assert f"<location>{tmp_path / 'date' / 'SKILL.md'}</location>" in text


def test_prompt_tells_the_model_to_read_then_run_scripts(tmp_path: Path) -> None:
    text = format_skills_for_system_prompt([_skill("date", "dates", tmp_path)])

    assert "read" in text
    assert "bash" in text
    assert "SKILL.md" in text


def test_escapes_xml_special_characters_in_names_and_descriptions(tmp_path: Path) -> None:
    text = format_skills_for_system_prompt([_skill("d<a>te", 'a < b & "c"', tmp_path)])

    assert "d&lt;a&gt;te" in text
    assert "a &lt; b &amp; &quot;c&quot;" in text
