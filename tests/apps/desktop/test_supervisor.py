from pathlib import Path

from apps.desktop.config import DesktopConfig
from apps.desktop.supervisor import ServiceSupervisor


class FakeProcess:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.pid = 4242
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeProcessFactory:
    def __init__(self) -> None:
        self.calls = []
        self.processes: list[FakeProcess] = []

    def __call__(self, command, **kwargs):
        process = FakeProcess(list(command))
        self.processes.append(process)
        self.calls.append(kwargs)
        return process


def _config(tmp_path: Path) -> DesktopConfig:
    root = tmp_path
    next_bin = root / "apps" / "web" / "node_modules" / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    next_bin.chmod(0o755)
    return DesktopConfig.from_env(root=root, env={"OPENTALOS_DESKTOP_WEB_MODE": "dev"})


def test_supervisor_reuses_healthy_services(tmp_path: Path) -> None:
    factory = FakeProcessFactory()
    supervisor = ServiceSupervisor(
        _config(tmp_path),
        process_factory=factory,
        health_check=lambda *_args: True,
        sleep=lambda _seconds: None,
    )

    supervisor.start()

    assert factory.processes == []
    assert supervisor.managed_services == ()
    supervisor.stop()


def test_supervisor_starts_and_stops_api_then_web(tmp_path: Path) -> None:
    factory = FakeProcessFactory()
    health_calls = 0

    def health_check(*_args) -> bool:
        nonlocal health_calls
        health_calls += 1
        return health_calls % 2 == 0

    supervisor = ServiceSupervisor(
        _config(tmp_path),
        process_factory=factory,
        health_check=health_check,
        sleep=lambda _seconds: None,
    )

    supervisor.start()

    assert [process.command[0].split("/")[-1] for process in factory.processes] == ["python", "next"]
    assert "apps/api" in " ".join(factory.processes[0].command)
    assert "dev" in factory.processes[1].command
    assert supervisor.managed_services == ("api", "web")

    supervisor.stop()

    assert all(process.terminated for process in factory.processes)


def test_supervisor_status_reports_process_health(tmp_path: Path) -> None:
    supervisor = ServiceSupervisor(
        _config(tmp_path),
        process_factory=FakeProcessFactory(),
        health_check=lambda url, _expect_json: url.endswith("/health"),
        sleep=lambda _seconds: None,
    )

    status = supervisor.status()

    assert status["api"] is True
    assert status["web"] is False
