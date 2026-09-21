import time
from pathlib import Path

import docker
import pytest

from sandbox import PathValidationError, resolve_interpreter, resolve_script_path, run_sandboxed_script


@pytest.fixture(scope="session")
def docker_client():
    return docker.from_env()


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    d = tmp_path / "greeter"
    d.mkdir()
    (d / "greet.js").write_text('console.log("hello, " + process.argv[2]);', encoding="utf-8")
    return d


def test_resolve_script_path_accepts_a_valid_relative_path(skill_dir: Path) -> None:
    resolved = resolve_script_path(skill_dir, "greet.js")
    assert resolved == (skill_dir / "greet.js").resolve()


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
    (evil_dir / "x.js").write_text('console.log("should not run");', encoding="utf-8")

    with pytest.raises(PathValidationError, match="outside"):
        resolve_script_path(skill_dir, "../greeter-evil/x.js")


def test_resolve_script_path_rejects_a_symlink_escaping_the_skill_dir(tmp_path: Path) -> None:
    skill_dir = tmp_path / "greeter"
    skill_dir.mkdir()
    outside_secret = tmp_path / "outside-secret.js"
    outside_secret.write_text('console.log("PWNED");', encoding="utf-8")
    symlink_path = skill_dir / "innocuous-link.js"
    symlink_path.symlink_to(outside_secret)

    with pytest.raises(PathValidationError, match="outside"):
        resolve_script_path(skill_dir, "innocuous-link.js")


def test_resolve_interpreter_maps_known_extensions() -> None:
    assert resolve_interpreter(Path("x.js")) == ("node", ".js")
    assert resolve_interpreter(Path("x.mjs")) == ("node", ".mjs")
    assert resolve_interpreter(Path("x.cjs")) == ("node", ".cjs")
    assert resolve_interpreter(Path("x.py")) == ("python3", ".py")


def test_resolve_interpreter_rejects_an_unsupported_extension_immediately() -> None:
    start = time.monotonic()
    with pytest.raises(PathValidationError, match="[Uu]nsupported script type"):
        resolve_interpreter(Path("x.sh"))
    assert time.monotonic() - start < 0.1


async def test_run_sandboxed_script_executes_a_js_script_and_captures_stdout(docker_client, skill_dir: Path) -> None:
    script_path = resolve_script_path(skill_dir, "greet.js")
    result = await run_sandboxed_script(docker_client, script_path, ["world"], None, 30_000)
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello, world"


async def test_run_sandboxed_script_writes_input_text_and_the_script_can_read_it(docker_client, tmp_path: Path) -> None:
    skill_dir = tmp_path / "echoer"
    skill_dir.mkdir()
    (skill_dir / "echo.py").write_text(
        "try:\n"
        '    with open("/scratch/input.txt") as f:\n'
        "        print(f.read())\n"
        "except FileNotFoundError:\n"
        '    print("no input")\n',
        encoding="utf-8",
    )
    script_path = resolve_script_path(skill_dir, "echo.py")
    result = await run_sandboxed_script(docker_client, script_path, [], "hello from input", 30_000)
    assert result.stdout.strip() == "hello from input"


async def test_run_sandboxed_script_has_no_network_access(docker_client, tmp_path: Path) -> None:
    skill_dir = tmp_path / "networker"
    skill_dir.mkdir()
    (skill_dir / "check.js").write_text(
        'const http = require("node:http");\n'
        'const req = http.get("http://example.com", { timeout: 3000 }, (res) => {\n'
        "  console.log(`REACHED:${res.statusCode}`);\n"
        "  process.exit(0);\n"
        "});\n"
        'req.on("error", (error) => {\n'
        "  console.log(`BLOCKED:${error.code ?? error.message}`);\n"
        "  process.exit(0);\n"
        "});\n"
        'req.on("timeout", () => {\n'
        '  console.log("BLOCKED:timeout");\n'
        "  req.destroy();\n"
        "  process.exit(0);\n"
        "});\n",
        encoding="utf-8",
    )
    script_path = resolve_script_path(skill_dir, "check.js")
    result = await run_sandboxed_script(docker_client, script_path, [], None, 30_000)
    assert result.stdout.strip().startswith("BLOCKED:")


async def test_run_sandboxed_script_kills_the_container_on_timeout(docker_client, tmp_path: Path) -> None:
    skill_dir = tmp_path / "looper"
    skill_dir.mkdir()
    (skill_dir / "loop.js").write_text("setInterval(() => {}, 1000);", encoding="utf-8")
    script_path = resolve_script_path(skill_dir, "loop.js")
    result = await run_sandboxed_script(docker_client, script_path, [], None, 2_000)
    assert result.timed_out is True
