import re
import shutil
from pathlib import Path

from .discovery import _extract_description
from .execution import PathValidationError, resolve_script_path
from .models import GithubImportSkipped, GithubSkillCandidate

GITHUB_REPO_URL_PATTERN = re.compile(r"^https://github\.com/[\w.\-]+/[\w.\-]+(?:\.git)?/?$")


class GithubImportError(RuntimeError):
    """repo_url 格式不对、clone 失败等，message 直接透传给调用方（路由层据此选 400 还是 502）。"""


def validate_repo_url(repo_url: str) -> None:
    if not GITHUB_REPO_URL_PATTERN.match(repo_url):
        raise GithubImportError(
            f'"{repo_url}" 不是一个合法的 GitHub 仓库 URL，格式应为 https://github.com/<owner>/<repo>。'
        )


def scan_repo(repo_dir: Path) -> list[GithubSkillCandidate]:
    candidates = []
    for skill_md in sorted(repo_dir.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        content = skill_md.read_text(encoding="utf-8")
        candidates.append(GithubSkillCandidate(
            relative_path=str(skill_dir.relative_to(repo_dir)),
            name=skill_dir.name,
            description=_extract_description(content),
        ))
    return candidates


def import_selected(
    repo_dir: Path, relative_paths: list[str], skills_root: Path
) -> tuple[list[str], list[GithubImportSkipped]]:
    imported: list[str] = []
    skipped: list[GithubImportSkipped] = []
    for relative_path in relative_paths:
        try:
            # resolve_script_path 对"不可信相对路径必须落在某个根目录之内"完全通用，
            # repo_dir 在这里就是那个根目录——不需要另写一套路径校验。
            source = resolve_script_path(repo_dir, relative_path)
        except PathValidationError:
            skipped.append(GithubImportSkipped(name=relative_path, reason="非法路径"))
            continue
        name = source.name
        destination = skills_root / name
        if destination.exists():
            skipped.append(GithubImportSkipped(name=name, reason="本地已存在同名技能"))
            continue
        shutil.copytree(source, destination)
        imported.append(name)
    return imported, skipped
