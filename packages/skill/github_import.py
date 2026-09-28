import re

GITHUB_REPO_URL_PATTERN = re.compile(r"^https://github\.com/[\w.\-]+/[\w.\-]+(?:\.git)?/?$")


class GithubImportError(RuntimeError):
    """repo_url 格式不对、clone 失败等，message 直接透传给调用方（路由层据此选 400 还是 502）。"""


def validate_repo_url(repo_url: str) -> None:
    if not GITHUB_REPO_URL_PATTERN.match(repo_url):
        raise GithubImportError(
            f'"{repo_url}" 不是一个合法的 GitHub 仓库 URL，格式应为 https://github.com/<owner>/<repo>。'
        )
