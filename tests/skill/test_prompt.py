from skill.models import SkillSummary
from skill.prompt import format_skills_for_system_prompt


def test_empty_skill_list_renders_nothing():
    assert format_skills_for_system_prompt([]) == ""


def test_renders_available_skills_block_with_names_and_descriptions():
    skills = [
        SkillSummary(name="date", description="计算相对于今天的日期。"),
        SkillSummary(name="csv-to-json", description="Convert CSV text to JSON."),
    ]

    text = format_skills_for_system_prompt(skills)

    assert "<available_skills>" in text
    assert "</available_skills>" in text
    assert "<name>date</name>" in text
    assert "<description>计算相对于今天的日期。</description>" in text
    assert "<name>csv-to-json</name>" in text


def test_prompt_tells_the_model_how_to_load_and_run_skills():
    text = format_skills_for_system_prompt([SkillSummary(name="date", description="dates")])

    assert "read_skill" in text
    assert "run_skill_script" in text


def test_escapes_xml_special_characters_in_names_and_descriptions():
    skills = [SkillSummary(name="d<a>te", description='a < b & "c"')]

    text = format_skills_for_system_prompt(skills)

    assert "d&lt;a&gt;te" in text
    assert "a &lt; b &amp; &quot;c&quot;" in text
