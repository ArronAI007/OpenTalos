import io
import zipfile
from pathlib import Path

import pytest

from skill.skill_upload import SkillUploadError, extract_uploaded_skill


def _build_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        for name, content in files.items():
            zip_file.writestr(name, content)
    return buffer.getvalue()


def _skill_md(name: str, description: str = "desc") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n"


def test_extract_uploaded_skill_succeeds(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    zip_bytes = _build_zip({"SKILL.md": _skill_md("my-skill"), "scripts/main.py": "print('hi')"})

    name = extract_uploaded_skill(zip_bytes, skills_root)

    assert name == "my-skill"
    assert (skills_root / "my-skill" / "SKILL.md").is_file()
    assert (skills_root / "my-skill" / "scripts" / "main.py").is_file()


def test_extract_uploaded_skill_rejects_missing_skill_md(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    zip_bytes = _build_zip({"README.md": "not a skill"})

    with pytest.raises(SkillUploadError, match="没有 SKILL.md"):
        extract_uploaded_skill(zip_bytes, skills_root)


def test_extract_uploaded_skill_rejects_missing_name_field(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    zip_bytes = _build_zip({"SKILL.md": "# no frontmatter here\n"})

    with pytest.raises(SkillUploadError, match="name 字段"):
        extract_uploaded_skill(zip_bytes, skills_root)


def test_extract_uploaded_skill_rejects_unsafe_name(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    zip_bytes = _build_zip({"SKILL.md": _skill_md("../evil")})

    with pytest.raises(SkillUploadError, match="不合法"):
        extract_uploaded_skill(zip_bytes, skills_root)


def test_extract_uploaded_skill_rejects_name_collision(tmp_path: Path):
    skills_root = tmp_path / "skills"
    (skills_root / "my-skill").mkdir(parents=True)
    zip_bytes = _build_zip({"SKILL.md": _skill_md("my-skill")})

    with pytest.raises(SkillUploadError, match="已存在同名技能"):
        extract_uploaded_skill(zip_bytes, skills_root)


def test_extract_uploaded_skill_rejects_zip_slip(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    zip_bytes = _build_zip({"SKILL.md": _skill_md("my-skill"), "../../evil.txt": "pwned"})

    with pytest.raises(SkillUploadError, match="不合法"):
        extract_uploaded_skill(zip_bytes, skills_root)


def test_extract_uploaded_skill_rejects_oversized_upload(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    huge_bytes = b"x" * (5 * 1024 * 1024 + 1)

    with pytest.raises(SkillUploadError, match="上限"):
        extract_uploaded_skill(huge_bytes, skills_root)


def test_extract_uploaded_skill_rejects_invalid_zip(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    with pytest.raises(SkillUploadError, match="不是合法的 zip"):
        extract_uploaded_skill(b"not a zip file", skills_root)
