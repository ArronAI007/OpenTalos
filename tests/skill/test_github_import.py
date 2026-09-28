import asyncio
from pathlib import Path

import pytest

from skill.github_import import (
    GithubImportError,
    clone_repo,
    import_github_skills,
    import_selected,
    scan_github_repo,
    scan_repo,
    validate_repo_url,
)


def test_validate_repo_url_accepts_a_plain_repo_url():
    validate_repo_url("https://github.com/anthropics/skills")  # 不抛异常即通过


def test_validate_repo_url_accepts_a_dot_git_suffix():
    validate_repo_url("https://github.com/anthropics/skills.git")


def test_validate_repo_url_rejects_a_url_with_a_subpath():
    with pytest.raises(GithubImportError, match="不是一个合法的 GitHub 仓库 URL"):
        validate_repo_url("https://github.com/anthropics/skills/tree/main/foo")


def test_validate_repo_url_rejects_a_non_github_host():
    with pytest.raises(GithubImportError, match="不是一个合法的 GitHub 仓库 URL"):
        validate_repo_url("https://gitlab.com/anthropics/skills")


def test_validate_repo_url_rejects_garbage():
    with pytest.raises(GithubImportError):
        validate_repo_url("not a url; rm -rf /")


def _write_skill(root: Path, relative_dir: str, body: str = "# skill\n\nA skill.\n") -> None:
    skill_dir = root / relative_dir
    # exist_ok=True：relative_dir="."（仓库根目录本身就是技能）时 root 已经存在（tmp_path 自带）。
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def test_scan_repo_finds_a_skill_at_the_repo_root(tmp_path: Path):
    _write_skill(tmp_path, ".", "# root-skill\n\nDoes root things.\n")

    candidates = scan_repo(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].relative_path == "."
    assert candidates[0].name == tmp_path.name
    assert candidates[0].description == "Does root things."


def test_scan_repo_finds_deeply_nested_skills(tmp_path: Path):
    _write_skill(tmp_path, "skills/alpha", "# alpha\n\nAlpha thing.\n")
    _write_skill(tmp_path, "skills/beta", "# beta\n\nBeta thing.\n")
    (tmp_path / "README.md").write_text("not a skill", encoding="utf-8")

    candidates = scan_repo(tmp_path)

    assert {c.name for c in candidates} == {"alpha", "beta"}
    assert {c.relative_path for c in candidates} == {"skills/alpha", "skills/beta"}


def test_scan_repo_returns_empty_list_for_a_repo_with_no_skills(tmp_path: Path):
    (tmp_path / "README.md").write_text("nothing here", encoding="utf-8")

    assert scan_repo(tmp_path) == []


def test_import_selected_copies_matching_directories(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    _write_skill(repo_dir, "skills/alpha", "# alpha\n\nAlpha thing.\n")
    (repo_dir / "skills/alpha/script.py").write_text("print('hi')", encoding="utf-8")
    skills_root = tmp_path / "skills_root"
    skills_root.mkdir()

    imported, skipped = import_selected(repo_dir, ["skills/alpha"], skills_root)

    assert imported == ["alpha"]
    assert skipped == []
    assert (skills_root / "alpha" / "SKILL.md").is_file()
    assert (skills_root / "alpha" / "script.py").is_file()


def test_import_selected_skips_a_name_that_already_exists_locally(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    _write_skill(repo_dir, "skills/alpha")
    skills_root = tmp_path / "skills_root"
    (skills_root / "alpha").mkdir(parents=True)  # 本地已有同名技能

    imported, skipped = import_selected(repo_dir, ["skills/alpha"], skills_root)

    assert imported == []
    assert len(skipped) == 1
    assert skipped[0].name == "alpha"
    assert "已存在" in skipped[0].reason


def test_import_selected_rejects_path_traversal(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skills_root = tmp_path / "skills_root"
    skills_root.mkdir()

    imported, skipped = import_selected(repo_dir, ["../../../etc"], skills_root)

    assert imported == []
    assert len(skipped) == 1
    assert skipped[0].reason == "非法路径"


def test_import_selected_handles_a_mix_of_success_and_conflict(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    _write_skill(repo_dir, "skills/alpha")
    _write_skill(repo_dir, "skills/beta")
    skills_root = tmp_path / "skills_root"
    (skills_root / "beta").mkdir(parents=True)  # beta 冲突，alpha 不冲突

    imported, skipped = import_selected(repo_dir, ["skills/alpha", "skills/beta"], skills_root)

    assert imported == ["alpha"]
    assert [s.name for s in skipped] == ["beta"]


class _FakeProcess:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


async def test_clone_repo_raises_a_clear_error_when_git_fails(monkeypatch, tmp_path: Path):
    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=128, stderr=b"fatal: repository not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(GithubImportError, match="repository not found"):
        await clone_repo("https://github.com/owner/does-not-exist", tmp_path / "dest")


async def test_scan_github_repo_clones_then_scans(monkeypatch):
    async def fake_clone_repo(repo_url: str, dest: Path) -> None:
        _write_skill(dest, "skills/alpha", "# alpha\n\nAlpha thing.\n")

    monkeypatch.setattr("skill.github_import.clone_repo", fake_clone_repo)

    candidates = await scan_github_repo("https://github.com/owner/repo")

    assert [c.name for c in candidates] == ["alpha"]


async def test_import_github_skills_clones_then_imports(monkeypatch, tmp_path: Path):
    async def fake_clone_repo(repo_url: str, dest: Path) -> None:
        _write_skill(dest, "skills/alpha", "# alpha\n\nAlpha thing.\n")

    monkeypatch.setattr("skill.github_import.clone_repo", fake_clone_repo)
    skills_root = tmp_path / "skills_root"
    skills_root.mkdir()

    imported, skipped = await import_github_skills("https://github.com/owner/repo", ["skills/alpha"], skills_root)

    assert imported == ["alpha"]
    assert skipped == []
