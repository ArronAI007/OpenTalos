from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .frontmatter import parse_frontmatter


@dataclass
class Skill:
    name: str
    description: str
    content: str
    dir: Path
    updated_at: str


def _extract_description(content: str) -> str:
    """优先取 SKILL.md 开头 YAML frontmatter 里的 description 字段；没有 frontmatter 或没有
    这个字段时，退回到取正文里第一个一级标题之后的第一行非空文本作为简短描述。"""
    frontmatter, body = parse_frontmatter(content)
    description = frontmatter.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            for next_line in lines[i + 1 :]:
                stripped = next_line.strip()
                if stripped:
                    return stripped
            break
    return ""


def list_skill_files(skill_dir: Path) -> list[tuple[str, str | None]]:
    """列出技能目录下所有文件的相对路径和内容——按 UTF-8 解码，解不出来（二进制文件）就给 None，
    调用方决定怎么展示"无法预览"，不在这里替调用方下判断。"""
    files = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir).as_posix()
        try:
            content: str | None = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = None
        files.append((relative, content))
    return files


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
        updated_at = datetime.fromtimestamp(skill_md.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        skills.append(Skill(
            name=entry.name, description=_extract_description(content), content=content,
            dir=entry, updated_at=updated_at,
        ))
    return skills
