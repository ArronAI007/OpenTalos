from pathlib import Path

from agent_platform.catalog import load_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_covers_all_pinned_agents_with_a_compatibility_path() -> None:
    agents = load_catalog()

    assert len(agents) == 87
    assert len({agent.id for agent in agents}) == 87
    assert all(agent.compatibility_path for agent in agents)
    assert all(agent.install_hint for agent in agents)
    assert all(agent.catalog_source for agent in agents)

    claude = next(agent for agent in agents if agent.name == "Claude Code")
    codex = next(agent for agent in agents if agent.name == "Codex")

    assert claude.config_format == "claude-settings"
    assert "claude" in claude.commands
    assert codex.config_format == "codex-toml"
    assert "codex" in codex.commands


def test_catalog_marks_manual_agents_as_configuration_unsupported() -> None:
    agents = load_catalog()

    manual = next(agent for agent in agents if agent.name == "Kun")
    assert manual.compatibility == "manual"
    assert manual.supports_configuration is False
    assert "Gateway" in manual.compatibility_path
