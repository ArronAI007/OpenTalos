"""Lifecycle management for the desktop app's local API and web services."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from apps.desktop.config import DesktopConfig, ServiceSpec


class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...


ProcessFactory = Callable[..., ProcessLike]
HealthCheck = Callable[[str, bool], bool]


class ServiceStartError(RuntimeError):
    """Raised when a supervised service exits or misses its startup deadline."""


@dataclass
class _Managed:
    process: ProcessLike
    log: IO[str]


class ServiceSupervisor:
    """Start, health-check, and stop the local services used by the desktop shell."""

    def __init__(
        self,
        config: DesktopConfig,
        *,
        process_factory: ProcessFactory = subprocess.Popen,
        health_check: HealthCheck | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._process_factory = process_factory
        self._health_check = health_check or _http_health
        self._sleep = sleep
        self._clock = clock
        self._services: dict[str, _Managed] = {}

    @property
    def managed_services(self) -> tuple[str, ...]:
        return tuple(self._services)

    def start(self) -> None:
        """Start missing services in API-then-web order and wait for health."""

        for spec in self.config.services():
            if self._health_check(spec.health_url, spec.expect_json):
                continue
            try:
                self._start_one(spec)
            except Exception:
                self.stop()
                raise

    def stop(self) -> None:
        """Terminate only processes started by this supervisor."""

        for managed in reversed(tuple(self._services.values())):
            process = managed.process
            if process.poll() is None:
                _terminate_process(process)
                try:
                    process.wait(timeout=5)
                except Exception:
                    _kill_process(process)
                    process.wait(timeout=5)
            managed.log.close()
        self._services.clear()

    def status(self) -> dict[str, bool]:
        return {
            spec.name: self._health_check(spec.health_url, spec.expect_json)
            for spec in self.config.services()
        }

    def _start_one(self, spec: ServiceSpec) -> None:
        log_dir = self.config.root / ".data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"desktop-{spec.name}.log"
        log = log_path.open("a", encoding="utf-8")
        kwargs: dict[str, object] = {
            "cwd": spec.cwd,
            "env": spec.environment,
            "stdout": log,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            process = self._process_factory(list(spec.command), **kwargs)
        except Exception:
            log.close()
            raise
        self._services[spec.name] = _Managed(process=process, log=log)
        self._wait_until_healthy(spec, process)

    def _wait_until_healthy(self, spec: ServiceSpec, process: ProcessLike) -> None:
        deadline = self._clock() + spec.startup_timeout
        while self._clock() < deadline:
            if self._health_check(spec.health_url, spec.expect_json):
                return
            return_code = process.poll()
            if return_code is not None:
                raise ServiceStartError(
                    f"{spec.name} exited during startup with code {return_code}"
                )
            self._sleep(0.25)
        raise ServiceStartError(
            f"{spec.name} did not become healthy within {spec.startup_timeout:.0f}s"
        )


def _http_health(url: str, expect_json: bool) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if not 200 <= response.status < 400:
                return False
            if not expect_json:
                return True
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _terminate_process(process: ProcessLike) -> None:
    if os.name != "nt" and isinstance(process, subprocess.Popen):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.terminate()


def _kill_process(process: ProcessLike) -> None:
    if os.name != "nt" and isinstance(process, subprocess.Popen):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.kill()
