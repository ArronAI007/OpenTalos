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

    @property
    def location(self) -> Path:
        """SKILL.md 的绝对路径——pi 式方案里直接写进系统提示词的 <location>，
        模型据此用 read 工具打开它、并按里面的相对路径用 bash 跑脚本。"""
        return self.dir / "SKILL.md"


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
    """递归发现所有包含 SKILL.md 的目录（对齐 pi / Agent Skills 规范：目录即技能，
    技能名取目录名）。同名技能保留先发现的（排序后第一个），避免歧义。

    传入的 skills_root 应为绝对路径——Skill.location 会被原样写进系统提示词。
    """
    if not skills_root.is_dir():
        return []
    skills: list[Skill] = []
    seen: set[str] = set()
    for skill_md in sorted(skills_root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        name = skill_dir.name
        if name in seen:
            continue
        seen.add(name)
        content = skill_md.read_text(encoding="utf-8")
        updated_at = datetime.fromtimestamp(skill_md.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        skills.append(Skill(
            name=name, description=_extract_description(content), content=content,
            dir=skill_dir, updated_at=updated_at,
        ))
    return skills
