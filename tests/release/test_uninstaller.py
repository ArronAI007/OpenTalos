from pathlib import Path

from release_platform.uninstaller import SafeUninstaller


def test_uninstall_restores_managed_agent_files_and_keeps_data(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "managed"\n', encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "chat.db").write_bytes(b"database")
    uninstaller = SafeUninstaller(
        data_dir=data,
        app_dir=tmp_path / "app",
        resource_root=tmp_path / "resources",
        snapshot_restorer=lambda: [{"path": str(config), "existed": True, "content": b"original\n"}],
    )

    result = uninstaller.run(keep_data=True)

    assert config.read_bytes() == b"original\n"
    assert (data / "chat.db").exists()
    assert result["restored_agents"] == 1
    assert result["data_removed"] is False


def test_purge_removes_user_data_but_never_touches_external_agent_files_without_snapshot(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "chat.db").write_bytes(b"database")
    uninstaller = SafeUninstaller(
        data_dir=data,
        app_dir=tmp_path / "app",
        resource_root=tmp_path / "resources",
        snapshot_restorer=lambda: [],
    )

    result = uninstaller.run(keep_data=False)

    assert not data.exists()
    assert result["data_removed"] is True
