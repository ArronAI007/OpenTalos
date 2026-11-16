"""Validate the pinned Magpie parity manifest used by the Python desktop port."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = Path("specs/007-magpie-python-parity")
EXPECTED_MAGPIE_COMMIT = "9dcec6751323674bc1ad9f52b13ec8fc081b4de6"
REQUIRED_AREAS = {
    "accounts",
    "agents",
    "control_plane",
    "desktop",
    "gateway",
    "operations",
    "privacy",
    "release",
    "routing",
    "sharing",
    "tools",
    "usage",
}


class BaselineError(ValueError):
    """Raised when the parity baseline violates its tracked contract."""


def _resolve_path(baseline_dir: Path) -> Path:
    return baseline_dir if baseline_dir.is_absolute() else REPO_ROOT / baseline_dir


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BaselineError(f"missing baseline artifact: {path}") from error
    except json.JSONDecodeError as error:
        raise BaselineError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(data, dict):
        raise BaselineError(f"{path} must contain a JSON object")
    return data


def load_baseline(baseline_dir: Path = BASELINE_DIR) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the manifest and agent catalog from a baseline directory."""

    root = _resolve_path(baseline_dir)
    manifest = _load_json(root / "capability-manifest.json")
    catalog = _load_json(root / "agent-catalog.json")
    return manifest, catalog


def _validate_manifest_shape(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise BaselineError(f"manifest schema validation failed: {rendered}")


def validate_baseline(baseline_dir: Path = BASELINE_DIR) -> dict[str, Any]:
    """Validate baseline integrity and return a compact summary."""

    root = _resolve_path(baseline_dir)
    manifest, catalog = load_baseline(baseline_dir)
    schema = _load_json(root / "capability-manifest.schema.json")
    _validate_manifest_shape(manifest, schema)

    upstream = manifest["upstream"]
    if upstream["commit"] != EXPECTED_MAGPIE_COMMIT:
        raise BaselineError(
            f"upstream commit changed without a new baseline: {upstream['commit']}"
        )

    capabilities = manifest["capabilities"]
    ids = [capability["id"] for capability in capabilities]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise BaselineError(f"duplicate capability ids: {', '.join(duplicates)}")

    areas = {capability["area"] for capability in capabilities}
    if areas != REQUIRED_AREAS:
        missing = sorted(REQUIRED_AREAS - areas)
        extra = sorted(areas - REQUIRED_AREAS)
        raise BaselineError(f"area coverage mismatch; missing={missing}, extra={extra}")

    agents = catalog["agents"]
    if len(agents) < 80:
        raise BaselineError(f"agent catalog is incomplete: found {len(agents)}")
    if len(agents) != len(set(agents)):
        raise BaselineError("agent catalog contains duplicate names")
    if EXPECTED_MAGPIE_COMMIT not in catalog["source"]:
        raise BaselineError("agent catalog source is not pinned to the baseline commit")
    if "agents.supported_catalog" not in ids:
        raise BaselineError("manifest does not track the supported-agent catalog")

    open_talos = manifest["open_talos"]
    if len(open_talos["commit"]) != 40:
        raise BaselineError("OpenTalos baseline commit must be a full Git SHA")

    return {
        "baseline_id": manifest["baseline_id"],
        "upstream_commit": upstream["commit"],
        "open_talos_commit": open_talos["commit"],
        "capability_count": len(capabilities),
        "agent_count": len(agents),
        "area_counts": dict(sorted(Counter(c["area"] for c in capabilities).items())),
        "status_counts": dict(sorted(Counter(c["status"] for c in capabilities).items())),
        "priority_counts": dict(sorted(Counter(c["priority"] for c in capabilities).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=BASELINE_DIR,
        help=f"baseline directory (default: {BASELINE_DIR})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the validation summary as JSON",
    )
    args = parser.parse_args()

    try:
        report = validate_baseline(args.baseline_dir)
    except BaselineError as error:
        parser.exit(1, f"error: {error}\n")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "M0 baseline valid: "
            f"{report['capability_count']} capabilities, "
            f"{report['agent_count']} agents, "
            f"Magpie {report['upstream_commit'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
