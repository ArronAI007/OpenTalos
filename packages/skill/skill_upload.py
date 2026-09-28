import io
import re
import zipfile
from pathlib import Path

from .frontmatter import parse_frontmatter

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_SAFE_NAME_PATTERN = re.compile(r"^[\w.\-]+$")


class SkillUploadError(RuntimeError):
    """上传包格式不对、缺 SKILL.md、缺合法 name 字段等，message 直接透传给调用方。"""


def _is_safe_member(member: str) -> bool:
    """zip-slip 防护：拒绝绝对路径和含 .. 的条目名（解压前检查，此时目标文件还不存在，
    不能用 execution.py 的 resolve_script_path——那个要求路径已经真实存在才能 strict resolve）。"""
    if member.startswith("/") or member.startswith("\\"):
        return False
    return ".." not in Path(member).parts


def extract_uploaded_skill(file_bytes: bytes, skills_root: Path) -> str:
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise SkillUploadError(f"上传文件超过 {MAX_UPLOAD_BYTES} 字节上限。")

    try:
        zip_file = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as error:
        raise SkillUploadError("不是合法的 zip 压缩包。") from error

    if "SKILL.md" not in zip_file.namelist():
        raise SkillUploadError("压缩包根目录下没有 SKILL.md。")

    skill_md_content = zip_file.read("SKILL.md").decode("utf-8")
    frontmatter, _ = parse_frontmatter(skill_md_content)
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SkillUploadError("SKILL.md 缺少 YAML frontmatter 里的 name 字段。")
    name = name.strip()
    if not _SAFE_NAME_PATTERN.match(name):
        raise SkillUploadError(f'技能名字 "{name}" 不合法，只能包含字母、数字、点、下划线、连字符。')

    destination = skills_root / name
    if destination.exists():
        raise SkillUploadError(f'本地已存在同名技能 "{name}"。')

    for member in zip_file.namelist():
        if not _is_safe_member(member):
            raise SkillUploadError(f'压缩包内的路径 "{member}" 不合法。')

    destination.mkdir(parents=True)
    zip_file.extractall(destination)
    return name
