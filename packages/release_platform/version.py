"""Application release version constants shared by desktop and APIs."""

from __future__ import annotations

import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

CURRENT_DATA_SCHEMA_VERSION = 1


def app_version() -> str:
    override = os.environ.get("OPENTALOS_VERSION")
    if override:
        return override
    for root in _version_roots():
        metadata = root / "runtime" / "version.json"
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        value = payload.get("version") if isinstance(payload, dict) else None
        if isinstance(value, str) and value:
            return value
    try:
        return version("opentalos")
    except PackageNotFoundError:
        return "0.1.0"


def _version_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        roots.append(root)
        if sys.platform == "darwin" and root.name == "Frameworks":
            roots.append(root.parent / "Resources")
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parents[2])
    return tuple(dict.fromkeys(roots))
