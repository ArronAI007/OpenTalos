import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_core_boundary import Violation, find_boundary_violations  # noqa: E402


def test_the_real_packages_core_has_zero_violations():
    violations = find_boundary_violations(_REPO_ROOT / "packages" / "core")
    assert violations == []


def test_detects_an_import_from_a_disallowed_package(tmp_path):
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "agent.py").write_text(
        "import os\nfrom tool.registry import ToolRegistry\n",
        encoding="utf-8",
    )

    violations = find_boundary_violations(fake_core)

    assert len(violations) == 1
    violation = violations[0]
    assert isinstance(violation, Violation)
    assert violation.file == fake_core / "agent.py"
    assert violation.line == 2
    assert violation.imported_package == "tool"


def test_allows_stdlib_and_third_party_and_core_relative_imports(tmp_path):
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "model.py").write_text(
        "import asyncio\nimport json\nfrom openai import AsyncOpenAI\nfrom .protocol import ChatMessage\n",
        encoding="utf-8",
    )

    assert find_boundary_violations(fake_core) == []


def test_detects_violations_in_a_package_not_yet_known_about(tmp_path):
    # 白名单逻辑：即便是一个今天压根不存在的新功能包名，也应该被判定为违规。
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "agent.py").write_text(
        "from some_future_feature.thing import Whatever\n", encoding="utf-8"
    )

    violations = find_boundary_violations(fake_core)

    assert len(violations) == 1
    assert violations[0].imported_package == "some_future_feature"


def test_missing_package_directory_raises_a_clear_error():
    import pytest

    with pytest.raises(FileNotFoundError):
        find_boundary_violations(Path("/no/such/directory"))
