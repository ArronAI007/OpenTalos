from pathlib import Path

from scripts.check_magpie_parity import (
    BASELINE_DIR,
    EXPECTED_MAGPIE_COMMIT,
    load_baseline,
    validate_baseline,
)


def test_magpie_parity_baseline_is_valid() -> None:
    report = validate_baseline(BASELINE_DIR)

    assert report["upstream_commit"] == EXPECTED_MAGPIE_COMMIT
    assert report["capability_count"] >= 50
    assert report["agent_count"] >= 80
    assert report["status_counts"]["gap"] > 0


def test_magpie_commit_is_documented_in_m0_notes() -> None:
    notes = (BASELINE_DIR / "m0-baseline.md").read_text(encoding="utf-8")

    assert EXPECTED_MAGPIE_COMMIT in notes
    assert "OpenTalos" in notes
    assert "M0" in notes


def test_every_required_workstream_is_covered() -> None:
    manifest, _ = load_baseline(BASELINE_DIR)
    areas = {capability["area"] for capability in manifest["capabilities"]}

    assert areas == {
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


def test_agent_catalog_comes_from_pinned_readme() -> None:
    manifest, catalog = load_baseline(BASELINE_DIR)
    source = catalog["source"]

    assert EXPECTED_MAGPIE_COMMIT in source
    assert source.endswith("README.md#supported-agents")
    assert len(catalog["agents"]) == len(set(catalog["agents"]))
    assert any(
        capability["id"] == "agents.supported_catalog"
        for capability in manifest["capabilities"]
    )


def test_baseline_artifacts_are_repository_relative() -> None:
    baseline_dir = Path(BASELINE_DIR)

    assert not baseline_dir.is_absolute()
    assert baseline_dir.parts[:2] == ("specs", "007-magpie-python-parity")
