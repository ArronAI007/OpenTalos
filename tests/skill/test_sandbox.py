import asyncio
import os
import shutil

import pytest

from skill.sandbox import run_in_sandbox

# 真起容器：仅在装了 docker CLI 且显式设 RUN_DOCKER_TESTS=1 时运行（避免默认套件依赖 Docker）。
pytestmark = [
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed"),
    pytest.mark.skipif(os.environ.get("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 to run"),
]


@pytest.fixture(scope="module", autouse=True)
def _docker_daemon():
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"docker daemon unavailable: {error}")


def test_sandbox_runs_a_python_script(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello from sandbox')\n")

    result = asyncio.run(run_in_sandbox(script, [], None, 60_000))

    assert result.exit_code == 0
    assert "hello from sandbox" in result.stdout


def test_sandbox_pipes_input_text(tmp_path):
    script = tmp_path / "read_input.py"
    script.write_text("print(open('/scratch/input.txt').read())\n")

    result = asyncio.run(run_in_sandbox(script, [], "hello input", 60_000))

    assert "hello input" in result.stdout


def test_sandbox_has_no_network(tmp_path):
    script = tmp_path / "net.py"
    script.write_text(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except OSError:\n"
        "    print('NO_NETWORK')\n"
    )

    result = asyncio.run(run_in_sandbox(script, [], None, 60_000))

    assert "NO_NETWORK" in result.stdout


def test_sandbox_kills_a_script_that_times_out(tmp_path):
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(60)\n")

    result = asyncio.run(run_in_sandbox(script, [], None, 1500))

    assert result.timed_out is True
