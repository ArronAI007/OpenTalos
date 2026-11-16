"""Apply a staged desktop update after the current process releases its files."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


class InstallError(RuntimeError):
    pass


ProcessFactory = Callable[..., subprocess.Popen]


def install_request_path(data_dir: Path) -> Path:
    return Path(data_dir) / "updates" / "install-request.json"


def read_install_request(data_dir: Path) -> dict[str, Any] | None:
    path = install_request_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise InstallError(f"cannot read update install request: {error}") from error
    if not isinstance(payload, dict):
        raise InstallError("update install request must be a JSON object")
    artifact = Path(str(payload.get("artifact_path", "")))
    if not artifact.is_file():
        raise InstallError("requested update artifact is missing")
    expected = str(payload.get("sha256", ""))
    hasher = hashlib.sha256()
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != expected:
        raise InstallError("requested update artifact checksum changed")
    return payload


def apply_install_request(
    *,
    data_dir: Path,
    app_dir: Path,
    platform_name: str | None = None,
    process_factory: ProcessFactory = subprocess.Popen,
) -> bool:
    """Launch the platform updater. The caller must exit immediately afterwards."""

    request = read_install_request(data_dir)
    if request is None:
        return False
    artifact = Path(str(request["artifact_path"])).resolve()
    platform_value = platform_name or sys.platform
    if platform_value == "darwin":
        _launch_macos_installer(artifact, Path(app_dir).resolve(), process_factory)
    elif platform_value == "win32":
        _launch_windows_installer(artifact, process_factory)
    elif platform_value.startswith("linux"):
        _launch_linux_installer(artifact, process_factory)
    else:
        raise InstallError(f"automatic updates are not supported on {platform_value}")
    install_request_path(data_dir).unlink(missing_ok=True)
    return True


def _launch_macos_installer(
    artifact: Path,
    app_dir: Path,
    process_factory: ProcessFactory,
) -> None:
    if artifact.suffix.lower() != ".dmg":
        raise InstallError("macOS update artifact must be a DMG")
    if app_dir.suffix != ".app" or not app_dir.is_dir():
        raise InstallError("macOS update must run from an installed .app bundle")
    descriptor, helper_name = tempfile.mkstemp(
        prefix="opentalos-update-",
        suffix=".sh",
    )
    helper = Path(helper_name)
    script = f"""#!/bin/sh
set -eu
sleep 2
mount_point="$(mktemp -d /tmp/opentalos-dmg.XXXXXX)"
cleanup() {{
  hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
  rm -rf "$mount_point"
  rm -f "$0"
}}
trap cleanup EXIT
hdiutil attach {_shell_quote(str(artifact))} -nobrowse -readonly -mountpoint "$mount_point" -quiet
source_app="$(find "$mount_point" -maxdepth 1 -name '*.app' -print -quit)"
test -n "$source_app"
staged="{app_dir}.update"
previous="{app_dir}.previous"
rm -rf "$staged" "$previous"
ditto "$source_app" "$staged"
mv {_shell_quote(str(app_dir))} "$previous"
if ! mv "$staged" {_shell_quote(str(app_dir))}; then
  mv "$previous" {_shell_quote(str(app_dir))}
  exit 1
fi
open {_shell_quote(str(app_dir))}
rm -rf "$previous"
"""
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(script)
    helper.chmod(0o700)
    process_factory(
        ["/bin/sh", str(helper)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _launch_windows_installer(
    artifact: Path,
    process_factory: ProcessFactory,
) -> None:
    if artifact.suffix.lower() != ".exe":
        raise InstallError("Windows update artifact must be an installer EXE")
    process_factory(
        [
            str(artifact),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


def _launch_linux_installer(
    artifact: Path,
    process_factory: ProcessFactory,
) -> None:
    if artifact.suffix.lower() != ".deb":
        raise InstallError("Linux update artifact must be a DEB package")
    launcher = shutil.which("xdg-open")
    if launcher is None:
        raise InstallError("xdg-open is required to launch the Linux installer")
    process_factory(
        [launcher, str(artifact)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def current_platform() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform


def current_arch() -> str:
    value = platform.machine().lower()
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(value, value)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
