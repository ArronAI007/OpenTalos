from pathlib import Path

from agent_platform.catalog import AgentDefinition
from agent_platform.resources import discover_resources


def _definition(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        id="claude-code",
        name="Claude Code",
        commands=("claude",),
        config_paths={"darwin": (str(tmp_path / ".claude" / "settings.json"),)},
        config_format="claude-settings",
        compatibility="native",
        compatibility_path="Native Claude adapter",
        install_hint="install claude",
        update_plan={},
        resource_paths={
            "instructions": str(tmp_path / ".claude" / "CLAUDE.md"),
            "subagents": str(tmp_path / ".claude" / "agents" / "{name}.md"),
            "commands": str(tmp_path / ".claude" / "commands" / "{name}.md"),
        },
        catalog_source="test",
    )


def test_discovers_agent_instructions_subagents_commands_and_plugins(
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    (tmp_path / ".claude" / "CLAUDE.md").write_text(
        "# Global\nUse concise answers.",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "agents" / "reviewer.md").write_text(
        "---\ndescription: Reviews code\n---\nBe strict.",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "commands" / "ship.md").write_text(
        "Run tests and commit.",
        encoding="utf-8",
    )
    plugin = (
        tmp_path
        / ".claude"
        / "plugins"
        / "marketplaces"
        / "official"
        / "plugins"
        / "review"
        / ".claude-plugin"
    )
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        '{"name":"review","description":"Review tools","version":"1.0.0"}',
        encoding="utf-8",
    )
    magpie = tmp_path / ".config" / "magpie"
    magpie.mkdir(parents=True)
    (magpie / "library.json").write_text('{"instructions":{"agents":[]}}', encoding="utf-8")

    result = discover_resources(
        [_definition(tmp_path)],
        [
            {
                "id": "claude-code",
                "name": "Claude Code",
                "installed": True,
                "capabilities": ["instructions"],
            }
        ],
        home=tmp_path,
    )

    by_kind: dict[str, list[dict]] = {}
    for item in result["resources"]:
        by_kind.setdefault(item["kind"], []).append(item)
    assert {item["name"] for item in by_kind["instructions"]} == {"CLAUDE.md"}
    assert {item["name"] for item in by_kind["subagents"]} == {"reviewer"}
    assert {item["name"] for item in by_kind["commands"]} == {"ship"}
    assert {item["name"] for item in by_kind["plugins"]} == {
        "review",
        "library.json",
    }
    assert result["agents"][0]["id"] == "claude-code"


def test_skips_empty_and_uninstalled_agent_resources(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("", encoding="utf-8")

    result = discover_resources(
        [_definition(tmp_path)],
        [{"id": "claude-code", "name": "Claude Code", "installed": False}],
        home=tmp_path,
    )

    assert result["resources"] == []
    assert result["agents"] == []
