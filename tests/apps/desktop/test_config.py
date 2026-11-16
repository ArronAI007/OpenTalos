import sys
from pathlib import Path

import pytest

from apps.desktop.config import DesktopConfig, DesktopConfigError


def _write_next(root: Path) -> None:
    executable = root / "apps" / "web" / "node_modules" / ".bin" / "next"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)


def _write_build(root: Path) -> None:
    build_id = root / "apps" / "web" / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("test-build", encoding="utf-8")


def test_default_config_builds_loopback_services(tmp_path: Path) -> None:
    _write_next(tmp_path)
    _write_build(tmp_path)
    config = DesktopConfig.from_env(root=tmp_path, env={})

    assert config.api_url == "http://127.0.0.1:8400"
    assert config.gateway_url == "http://127.0.0.1:3425"
    assert config.web_url == "http://127.0.0.1:3010"
    assert config.web_mode == "start"
    assert config.api_command()[-2:] == ("--port", "8400")
    assert config.gateway_command()[-2:] == ("--port", "3425")
    assert config.web_command()[-5:] == ("start", "-H", "127.0.0.1", "-p", "3010")

    api_env = config.api_environment()
    assert str(tmp_path / "packages") in api_env["PYTHONPATH"].split(":")
    assert "http://127.0.0.1:3010" in api_env["CORS_ORIGINS"]

    web_env = config.web_environment()
    assert web_env["NEXT_PUBLIC_API_URL"] == config.api_url


def test_custom_api_port_forces_dev_mode_for_baked_next_build(tmp_path: Path) -> None:
    _write_next(tmp_path)
    _write_build(tmp_path)
    config = DesktopConfig.from_env(root=tmp_path, env={"API_PORT": "18400"})

    assert config.web_mode == "dev"
    assert config.web_command()[-5:] == ("dev", "-H", "127.0.0.1", "-p", "3010")


def test_explicit_web_mode_is_honored(tmp_path: Path) -> None:
    _write_next(tmp_path)
    _write_build(tmp_path)

    config = DesktopConfig.from_env(
        root=tmp_path,
        env={"OPENTALOS_DESKTOP_WEB_MODE": "dev"},
    )

    assert config.web_mode == "dev"
    assert config.services()[2].command[1] == "dev"


def test_config_requires_installed_next_executable(tmp_path: Path) -> None:
    config = DesktopConfig.from_env(root=tmp_path, env={})

    with pytest.raises(DesktopConfigError, match="next executable"):
        config.web_command()


def test_frozen_config_uses_bundled_node_and_internal_python_services(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    node = resources / "runtime" / "node" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)
    server = resources / "runtime" / "web" / "apps" / "web" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("console.log('web')\n", encoding="utf-8")
    data = tmp_path / "user-data"

    config = DesktopConfig.from_env(
        root=tmp_path,
        env={
            "OPENTALOS_FROZEN": "1",
            "OPENTALOS_RESOURCE_ROOT": str(resources),
            "OPENTALOS_DATA_DIR": str(data),
        },
    )

    assert config.frozen is True
    assert config.data_dir == data
    assert config.api_command()[:3] == (
        sys.executable,
        "--internal-service",
        "api",
    )
    assert config.gateway_command()[2] == "gateway"
    assert config.web_command() == (str(node), str(server))
    assert config.web_environment()["PORT"] == "3010"
    assert config.api_environment()["OPENTALOS_DATA_DIR"] == str(data)
