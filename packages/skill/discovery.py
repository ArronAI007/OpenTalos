from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    content: str
    dir: Path


def _extract_description(content: str) -> str:
    """取 SKILL.md 里第一个一级标题之后的第一行非空文本作为简短描述。"""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            for next_line in lines[i + 1 :]:
                stripped = next_line.strip()
                if stripped:
                    return stripped
            break
    return ""


def discover_skills(skills_root: Path) -> list[Skill]:
    if not skills_root.is_dir():
        return []
    skills = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        content = skill_md.read_text(encoding="utf-8")
        skills.append(Skill(name=entry.name, description=_extract_description(content), content=content, dir=entry))
    return skills
