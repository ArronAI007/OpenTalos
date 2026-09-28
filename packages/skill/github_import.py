import asyncio
import re
import shutil
import tempfile
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


async def clone_repo(repo_url: str, dest: Path) -> None:
    validate_repo_url(repo_url)
    process = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", repo_url, str(dest),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise GithubImportError(f"git clone 失败：{stderr.decode(errors='replace').strip()}")


async def scan_github_repo(repo_url: str) -> list[GithubSkillCandidate]:
    with tempfile.TemporaryDirectory() as tmp:
        # .resolve()：macOS 的系统临时目录在 /var/... 下，是 /private/var/... 的符号链接。
        # resolve_script_path 对 skill_dir 做纯文本前缀比对——不先解析这层符号链接，
        # 之后 import_selected 里的路径校验会把合法路径误判成"跳出根目录"。
        tmp_path = Path(tmp).resolve()
        await clone_repo(repo_url, tmp_path)
        return scan_repo(tmp_path)


async def import_github_skills(
    repo_url: str, relative_paths: list[str], skills_root: Path
) -> tuple[list[str], list[GithubImportSkipped]]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()  # 同上，避免符号链接导致路径前缀校验误判。
        await clone_repo(repo_url, tmp_path)
        return import_selected(tmp_path, relative_paths, skills_root)
