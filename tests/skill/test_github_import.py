import pytest

from skill.github_import import GithubImportError, validate_repo_url


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
