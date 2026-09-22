import sys
import time
from pathlib import Path

import pytest

from skill.execution import PathValidationError, execute_script, resolve_interpreter, resolve_script_path


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    d = tmp_path / "greeter"
    d.mkdir()
    (d / "greet.py").write_text("import sys; print('hello, ' + sys.argv[1])", encoding="utf-8")
    return d


def test_resolve_script_path_accepts_a_valid_relative_path(skill_dir: Path) -> None:
    resolved = resolve_script_path(skill_dir, "greet.py")
    assert resolved == (skill_dir / "greet.py").resolve()


def test_resolve_script_path_rejects_an_absolute_path(skill_dir: Path) -> None:
    with pytest.raises(PathValidationError, match="absolute paths"):
        resolve_script_path(skill_dir, "/etc/passwd")


def test_resolve_script_path_rejects_path_traversal(skill_dir: Path) -> None:
    with pytest.raises(PathValidationError, match="outside"):
        resolve_script_path(skill_dir, "../../../etc/passwd")


def test_resolve_script_path_rejects_a_sibling_directory_sharing_a_textual_prefix(tmp_path: Path) -> None:
    skill_dir = tmp_path / "greeter"
    skill_dir.mkdir()
    evil_dir = tmp_path / "greeter-evil"
    evil_dir.mkdir()
    (evil_dir / "x.py").write_text("print('should not run')", encoding="utf-8")

    with pytest.raises(PathValidationError, match="outside"):
        resolve_script_path(skill_dir, "../greeter-evil/x.py")


def test_resolve_script_path_rejects_a_symlink_escaping_the_skill_dir(tmp_path: Path) -> None:
    skill_dir = tmp_path / "greeter"
    skill_dir.mkdir()
    outside_secret = tmp_path / "outside-secret.py"
    outside_secret.write_text("print('PWNED')", encoding="utf-8")
    symlink_path = skill_dir / "innocuous-link.py"
    symlink_path.symlink_to(outside_secret)

    with pytest.raises(PathValidationError, match="outside"):
        resolve_script_path(skill_dir, "innocuous-link.py")


def test_resolve_interpreter_maps_known_extensions() -> None:
    assert resolve_interpreter(Path("x.js")) == ("node", ".js")
    assert resolve_interpreter(Path("x.mjs")) == ("node", ".mjs")
    assert resolve_interpreter(Path("x.cjs")) == ("node", ".cjs")
    # 宿主机直跑用服务进程自己的 Python，不赌 PATH 上有 python3
    assert resolve_interpreter(Path("x.py")) == (sys.executable, ".py")


def test_resolve_interpreter_rejects_an_unsupported_extension_immediately() -> None:
    start = time.monotonic()
    with pytest.raises(PathValidationError, match="[Uu]nsupported script type"):
        resolve_interpreter(Path("x.sh"))
    assert time.monotonic() - start < 0.1


async def test_execute_script_runs_the_script_with_args_and_captures_stdout(skill_dir: Path) -> None:
    result = await execute_script(resolve_script_path(skill_dir, "greet.py"), ["world"], None, 10_000)

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello, world"
    assert result.timed_out is False


async def test_execute_script_feeds_input_text_via_stdin(tmp_path: Path) -> None:
    (tmp_path / "echo.py").write_text("import sys; print(sys.stdin.read())", encoding="utf-8")

    result = await execute_script(tmp_path / "echo.py", [], "hello from input", 10_000)

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello from input"


async def test_execute_script_without_input_text_does_not_hang_on_stdin(tmp_path: Path) -> None:
    # 脚本主动读 stdin 而调用方没给 input_text 时，stdin 必须是 DEVNULL（立即 EOF），
    # 否则脚本会一直等输入直到超时。
    (tmp_path / "echo.py").write_text("import sys; print(f'got:[{sys.stdin.read()}]')", encoding="utf-8")

    result = await execute_script(tmp_path / "echo.py", [], None, 10_000)

    assert result.exit_code == 0
    assert result.stdout.strip() == "got:[]"


async def test_execute_script_reports_non_zero_exit_and_stderr(tmp_path: Path) -> None:
    (tmp_path / "fail.py").write_text("import sys; sys.stderr.write('boom'); sys.exit(3)", encoding="utf-8")

    result = await execute_script(tmp_path / "fail.py", [], None, 10_000)

    assert result.exit_code == 3
    assert result.stderr == "boom"
    assert result.timed_out is False


async def test_execute_script_kills_the_process_on_timeout(tmp_path: Path) -> None:
    (tmp_path / "loop.py").write_text("import time; time.sleep(60)", encoding="utf-8")

    result = await execute_script(tmp_path / "loop.py", [], None, 500)

    assert result.timed_out is True
    assert result.exit_code == -1
