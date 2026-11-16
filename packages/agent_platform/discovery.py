"""Installed Agent discovery with injectable process and filesystem boundaries."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from .catalog import AgentDefinition


class CommandResult(Protocol):
    returncode: int
    stdout: str


CommandRunner = Callable[[list[str]], CommandResult]
PathExists = Callable[[str], bool]
Which = Callable[[str], str | None]


class AgentDiscovery:
    def __init__(
        self,
        agents: Sequence[AgentDefinition],
        *,
        platform_name: str | None = None,
        home: Path | None = None,
        which: Which = shutil.which,
        path_exists: PathExists | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.agents = list(agents)
        self.platform_name = platform_name or sys.platform
        self.home = Path(home or Path.home())
        self._which = which
        self._path_exists = path_exists or os.path.exists
        self._command_runner = command_runner or _run_command

    def discover(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        definitions = [
            agent for agent in self.agents if agent_id is None or agent.id == agent_id
        ]
        discovered: list[dict[str, Any]] = []
        for definition in definitions:
            installation = self._discover_one(definition)
            if installation is not None:
                discovered.append(installation)
        return discovered

    def _discover_one(self, definition: AgentDefinition) -> dict[str, Any] | None:
        executable = next(
            (
                resolved
                for command in definition.commands
                if (resolved := self._which(command))
            ),
            None,
        )
        app_path = None
        if executable is None:
            app_path = next(
                (
                    path
                    for candidate in definition.app_paths.get(self.platform_name, ())
                    if (path := self._expand_path(candidate))
                    and self._path_exists(path)
                ),
                None,
            )
            if app_path is None:
                return None

        config_path = self._select_config_path(definition)
        return {
            "agent_id": definition.id,
            "name": definition.name,
            "installed": True,
            "version": (
                self._version(executable)
                if executable is not None
                else self._app_version(app_path)
            ),
            "install_path": executable or app_path,
            "install_source": "command" if executable is not None else "app-bundle",
            "config_path": config_path,
            "platform": self.platform_name,
            "compatibility": definition.compatibility,
            "compatibility_path": definition.compatibility_path,
            "install_hint": definition.install_hint,
        }

    def _select_config_path(self, definition: AgentDefinition) -> str | None:
        candidates = definition.config_paths.get(self.platform_name, ())
        expanded = [self._expand_path(path) for path in candidates]
        existing = next((path for path in expanded if self._path_exists(path)), None)
        return existing or (expanded[0] if expanded else None)

    def _expand_path(self, value: str) -> str:
        expanded = value.replace("${HOME}", str(self.home))
        expanded = re.sub(
            r"%([^%]+)%",
            lambda match: os.environ.get(match.group(1), match.group(0)),
            expanded,
        )
        expanded = os.path.expandvars(expanded)
        path = Path(os.path.expanduser(expanded))
        if path.is_absolute():
            return str(path)
        return str(self.home / path)

    def _version(self, executable: str) -> str | None:
        for arguments in (["--version"], ["version"]):
            try:
                result = self._command_runner([executable, *arguments])
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode != 0:
                continue
            output = str(result.stdout or "").strip()
            match = re.search(r"\b(?:v)?(\d+\.\d+(?:\.\d+)?(?:[-+][\w.-]+)?)\b", output)
            if match:
                return match.group(1)
        return None

    def _app_version(self, app_path: str | None) -> str | None:
        if not app_path or not app_path.endswith(".app"):
            return None
        info = Path(app_path) / "Contents" / "Info.plist"
        try:
            with info.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            return None
        version = payload.get("CFBundleShortVersionString")
        return str(version) if version else None


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )
