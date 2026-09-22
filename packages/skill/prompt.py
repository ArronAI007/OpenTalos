from collections.abc import Sequence
from html import escape

from .models import SkillSummary


def format_skills_for_system_prompt(skills: Sequence[SkillSummary]) -> str:
    """把技能清单渲染成系统提示词里的 <available_skills> 段（渐进披露）。

    参考 pi（earendil-works/pi）的做法：提示词里只列 name + description，模型看到
    匹配的任务后用 read_skill 工具读完整 SKILL.md，再按文档用 run_skill_script 执行
    脚本。技能按名字寻址、由 skill 服务执行，所以不需要 pi 那样的 <location> 路径。
    """
    if not skills:
        return ""

    lines = [
        "The following skills provide specialized instructions and runnable scripts for specific tasks.",
        "Use the read_skill tool to load a skill's full documentation when the task matches its "
        "description, then follow that documentation to run scripts with the run_skill_script tool.",
        "",
        "<available_skills>",
    ]
    for skill in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{escape(skill.name)}</name>")
        lines.append(f"    <description>{escape(skill.description)}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)
