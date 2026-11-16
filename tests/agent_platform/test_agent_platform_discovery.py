from pathlib import Path

from agent_platform.catalog import AgentDefinition
from agent_platform.discovery import AgentDiscovery


def _definition(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        id="demo",
        name="Demo Agent",
        commands=("demo-agent",),
        config_paths={"darwin": (str(tmp_path / "demo.json"),)},
        config_format="json-env",
        compatibility="native",
        compatibility_path="Native JSON adapter",
        install_hint="npm install -g demo-agent",
        update_plan={"npm": ("npm", "install", "-g", "demo-agent@latest")},
        resource_paths={},
        catalog_source="test",
    )


def test_discovery_reports_version_source_and_config(tmp_path: Path) -> None:
    executable = tmp_path / "demo-agent"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    config = tmp_path / "demo.json"
    config.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def run(command: list[str]):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = "demo-agent 2.4.1\n"

        return Result()

    discovery = AgentDiscovery(
        [_definition(tmp_path)],
        platform_name="darwin",
        which=lambda name: str(executable) if name == "demo-agent" else None,
        path_exists=lambda path: Path(path).exists(),
        command_runner=run,
    )

    result = discovery.discover()[0]

    assert result["installed"] is True
    assert result["version"] == "2.4.1"
    assert result["install_path"] == str(executable)
    assert result["install_source"] == "command"
    assert result["config_path"] == str(config)
    assert result["platform"] == "darwin"
    assert calls == [[str(executable), "--version"]]


def test_discovery_hides_missing_agents_from_installed_view(tmp_path: Path) -> None:
    discovery = AgentDiscovery(
        [_definition(tmp_path)],
        platform_name="linux",
        which=lambda _name: None,
        path_exists=lambda _path: False,
    )

    assert discovery.discover() == []


def test_discovery_supports_app_bundles_and_plist_versions(tmp_path: Path) -> None:
    app = tmp_path / "Demo.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        b'<plist version="1.0"><dict>'
        b"<key>CFBundleShortVersionString</key><string>4.5.0</string>"
        b"</dict></plist>"
    )
    base = _definition(tmp_path)
    definition = AgentDefinition(
        **{
            **base.__dict__,
            "commands": (),
            "app_paths": {"darwin": (str(app),)},
        }
    )
    discovery = AgentDiscovery(
        [definition],
        platform_name="darwin",
        which=lambda _name: None,
        path_exists=lambda path: Path(path).exists(),
    )

    result = discovery.discover()[0]

    assert result["install_source"] == "app-bundle"
    assert result["install_path"] == str(app)
    assert result["version"] == "4.5.0"
