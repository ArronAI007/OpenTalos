"""Configuration and service commands for the OpenTalos desktop shell."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class DesktopConfigError(RuntimeError):
    """Raised when the desktop app cannot construct a required local command."""


@dataclass(frozen=True)
class ServiceSpec:
    """One local service supervised by the desktop application."""

    name: str
    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    health_url: str
    expect_json: bool
    startup_timeout: float


@dataclass(frozen=True)
class DesktopConfig:
    """Resolved paths, ports, and child-process commands for the desktop app."""

    root: Path
    api_port: int
    gateway_port: int
    web_port: int
    host: str
    web_mode: str
    startup_timeout: float
    web_startup_timeout: float

    @classmethod
    def from_env(
        cls,
        *,
        root: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> DesktopConfig:
        source = dict(os.environ if env is None else env)
        repo_root = Path(root or Path(__file__).resolve().parents[2]).resolve()
        api_port = _read_int(source, "API_PORT", 8400)
        gateway_port = _read_int(source, "GATEWAY_PORT", 3425)
        web_port = _read_int(source, "WEB_PORT", 3010)
        host = source.get("OPENTALOS_DESKTOP_HOST", "127.0.0.1")

        requested_mode = source.get("OPENTALOS_DESKTOP_WEB_MODE", "auto")
        if requested_mode not in {"auto", "dev", "start"}:
            raise DesktopConfigError(
                "OPENTALOS_DESKTOP_WEB_MODE must be auto, dev, or start"
            )
        has_build = (repo_root / "apps" / "web" / ".next" / "BUILD_ID").is_file()
        # NEXT_PUBLIC_* values are compiled into a production build. A non-default
        # API port therefore requires the dev server so the URL is not stale.
        web_mode = (
            "start"
            if requested_mode == "auto" and has_build and api_port == 8400
            else "dev"
            if requested_mode == "auto"
            else requested_mode
        )

        return cls(
            root=repo_root,
            api_port=api_port,
            gateway_port=gateway_port,
            web_port=web_port,
            host=host,
            web_mode=web_mode,
            startup_timeout=float(source.get("OPENTALOS_DESKTOP_STARTUP_TIMEOUT", "90")),
            web_startup_timeout=float(
                source.get("OPENTALOS_DESKTOP_WEB_STARTUP_TIMEOUT", "240")
            ),
        )

    @property
    def api_url(self) -> str:
        return f"http://{self.host}:{self.api_port}"

    @property
    def web_url(self) -> str:
        return f"http://{self.host}:{self.web_port}"

    @property
    def gateway_url(self) -> str:
        return f"http://{self.host}:{self.gateway_port}"

    @property
    def web_executable(self) -> Path:
        return self.root / "apps" / "web" / "node_modules" / ".bin" / "next"

    def api_command(self) -> tuple[str, ...]:
        return (
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--app-dir",
            str(self.root / "apps" / "api"),
            "--host",
            self.host,
            "--port",
            str(self.api_port),
        )

    def web_command(self) -> tuple[str, ...]:
        if not self.web_executable.is_file():
            raise DesktopConfigError(
                f"next executable not found: {self.web_executable}; run pnpm -C apps/web install"
            )
        if self.web_mode == "start" and not (
            self.root / "apps" / "web" / ".next" / "BUILD_ID"
        ).is_file():
            raise DesktopConfigError("Next.js production build is missing; run pnpm -C apps/web build")
        return (
            str(self.web_executable),
            self.web_mode,
            "-H",
            self.host,
            "-p",
            str(self.web_port),
        )

    def gateway_command(self) -> tuple[str, ...]:
        return (
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--app-dir",
            str(self.root / "apps" / "gateway"),
            "--host",
            self.host,
            "--port",
            str(self.gateway_port),
        )

    def api_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        pythonpath = str(self.root / "packages")
        current = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{pythonpath}{os.pathsep}{current}" if current else pythonpath
        )
        environment["CORS_ORIGINS"] = ",".join(
            (
                self.web_url,
                f"http://localhost:{self.web_port}",
            )
        )
        return environment

    def web_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["NEXT_PUBLIC_API_URL"] = self.api_url
        environment["NEXT_PUBLIC_GATEWAY_URL"] = self.gateway_url
        environment.setdefault("NEXT_PUBLIC_AGENTRL_URL", "http://localhost:8420")
        environment.setdefault("NEXT_PUBLIC_DEEPRESEARCH_URL", "http://localhost:8441")
        return environment

    def gateway_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        pythonpath = str(self.root / "packages")
        current = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{pythonpath}{os.pathsep}{current}" if current else pythonpath
        )
        environment["GATEWAY_CORS_ORIGINS"] = ",".join(
            (self.web_url, f"http://localhost:{self.web_port}")
        )
        return environment

    def services(self) -> tuple[ServiceSpec, ServiceSpec, ServiceSpec]:
        return (
            ServiceSpec(
                name="api",
                command=self.api_command(),
                cwd=self.root,
                environment=self.api_environment(),
                health_url=f"{self.api_url}/health",
                expect_json=True,
                startup_timeout=self.startup_timeout,
            ),
            ServiceSpec(
                name="gateway",
                command=self.gateway_command(),
                cwd=self.root,
                environment=self.gateway_environment(),
                health_url=f"{self.gateway_url}/health",
                expect_json=True,
                startup_timeout=self.startup_timeout,
            ),
            ServiceSpec(
                name="web",
                command=self.web_command(),
                cwd=self.root / "apps" / "web",
                environment=self.web_environment(),
                health_url=self.web_url,
                expect_json=False,
                startup_timeout=self.web_startup_timeout,
            ),
        )


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise DesktopConfigError(f"{name} must be an integer") from error
    if not 1 <= value <= 65535:
        raise DesktopConfigError(f"{name} must be between 1 and 65535")
    return value
