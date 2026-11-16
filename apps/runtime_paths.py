"""Resolve bundled resources and per-user writable data for source and frozen builds."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP_DIR_NAME = "OpenTalos"
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root(
    *,
    frozen: bool | None = None,
    source_root: Path | None = None,
    env: Mapping[str, str] | None = None,
    meipass: Path | None = None,
) -> Path:
    source = os.environ if env is None else env
    override = source.get("OPENTALOS_RESOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    is_bundle = is_frozen() if frozen is None else frozen
    if is_bundle:
        root = meipass or getattr(sys, "_MEIPASS", None)
        if root is not None:
            resolved = Path(root).resolve()
            if sys.platform == "darwin" and resolved.name == "Frameworks":
                resources = resolved.parent / "Resources"
                if resources.is_dir():
                    return resources
            return resolved
        return Path(sys.executable).resolve().parent
    return Path(source_root or SOURCE_ROOT).resolve()


def user_data_dir(
    *,
    frozen: bool | None = None,
    source_root: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    source = dict(os.environ if env is None else env)
    override = source.get("OPENTALOS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    is_bundle = is_frozen() if frozen is None else frozen
    if not is_bundle:
        return Path(source_root or SOURCE_ROOT).resolve() / ".data"

    platform_value = platform_name or sys.platform
    home_path = Path(home or Path.home()).expanduser()
    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / APP_DIR_NAME
    if platform_value == "win32":
        base = Path(source.get("LOCALAPPDATA") or home_path / "AppData" / "Local")
        return base / APP_DIR_NAME
    xdg = source.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else home_path / ".local" / "share"
    return base / APP_DIR_NAME
