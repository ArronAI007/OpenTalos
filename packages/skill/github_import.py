import re
from pathlib import Path

from .discovery import _extract_description
from .models import GithubSkillCandidate

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
