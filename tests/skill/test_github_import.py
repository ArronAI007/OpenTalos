from pathlib import Path

import pytest

from skill.github_import import GithubImportError, scan_repo, validate_repo_url


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
