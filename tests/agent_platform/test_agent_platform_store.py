from pathlib import Path

from agent_platform.store import AgentPlatformStore


def test_binding_and_profile_round_trip(tmp_path: Path) -> None:
    store = AgentPlatformStore(tmp_path / "agent-platform.db")
    binding = store.set_binding(
        "codex",
        model="group/coding",
        shortlist=["group/coding", "openai/Work/gpt-5"],
        routing_preference="group/coding",
    )

    assert binding["model"] == "group/coding"
    assert store.get_binding("codex")["shortlist"] == [
        "group/coding",
        "openai/Work/gpt-5",
    ]

    profile = store.save_profile("Work")
    assert profile["payload"]["bindings"]["codex"]["model"] == "group/coding"

    store.set_binding("codex", model="openai/Other/gpt-5", shortlist=[])
    restored = store.apply_profile(profile["id"])

    assert restored["codex"]["model"] == "group/coding"
    assert store.get_binding("codex")["shortlist"][0] == "group/coding"


def test_original_config_snapshot_is_never_overwritten(tmp_path: Path) -> None:
    store = AgentPlatformStore(tmp_path / "agent-platform.db")
    config = tmp_path / "settings.json"
    config.write_bytes(b'{"owned": true}\n')

    first = store.capture_snapshot("demo", config)
    config.write_bytes(b'{"managed": true}\n')
    second = store.capture_snapshot("demo", config)

    assert first["id"] == second["id"]
    assert store.get_snapshot("demo", str(config))["content"] == b'{"owned": true}\n'
