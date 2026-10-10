from collections.abc import Sequence
from html import escape

from .discovery import Skill


def format_skills_for_system_prompt(skills: Sequence[Skill]) -> str:
    """把技能清单渲染成系统提示词里的 <available_skills> 段（渐进披露，pi 式方案）。

    提示词里只列 name + description + SKILL.md 的绝对路径，不塞正文。模型看到匹配的任务后，
    用 read 工具打开 <location> 指向的 SKILL.md，再按文档里的相对路径用 bash 工具执行脚本。
    技能就是普通的文件系统目录，不存在"技能服务"这一层。
    """
    if not skills:
        return ""

    lines = [
        "The following skills provide specialized instructions and runnable scripts for specific tasks.",
        "When a task matches a skill's description, use the read tool to open its SKILL.md at the "
        "<location> below, then follow that documentation and use the bash tool to run the skill's "
        "bundled scripts (paths in the SKILL.md are relative to the skill's directory).",
        "",
        "<available_skills>",
    ]
    for skill in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{escape(skill.name)}</name>")
        lines.append(f"    <description>{escape(skill.description)}</description>")
        lines.append(f"    <location>{escape(str(skill.location))}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)
