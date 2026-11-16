from pathlib import Path

import pytest

from apps.runtime_paths import resource_root, user_data_dir


def test_source_data_directory_stays_in_checkout(tmp_path: Path) -> None:
    data = user_data_dir(
        frozen=False,
        source_root=tmp_path,
        env={},
        platform_name="darwin",
        home=tmp_path / "home",
    )

    assert data == tmp_path / ".data"


def test_frozen_user_data_directory_uses_platform_conventions(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    assert user_data_dir(
        frozen=True,
        source_root=tmp_path / "app",
        env={},
        platform_name="darwin",
        home=home,
    ) == home / "Library" / "Application Support" / "OpenTalos"
    assert user_data_dir(
        frozen=True,
        source_root=tmp_path / "app",
        env={"LOCALAPPDATA": str(tmp_path / "local")},
        platform_name="win32",
        home=home,
    ) == tmp_path / "local" / "OpenTalos"
    assert user_data_dir(
        frozen=True,
        source_root=tmp_path / "app",
        env={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        platform_name="linux",
        home=home,
    ) == tmp_path / "xdg" / "OpenTalos"


def test_explicit_overrides_win_for_portable_installs(tmp_path: Path) -> None:
    data = user_data_dir(
        frozen=True,
        source_root=tmp_path / "app",
        env={"OPENTALOS_DATA_DIR": str(tmp_path / "portable-data")},
        platform_name="linux",
        home=tmp_path / "home",
    )
    resources = resource_root(
        frozen=True,
        source_root=tmp_path / "app",
        env={"OPENTALOS_RESOURCE_ROOT": str(tmp_path / "resources")},
        meipass=tmp_path / "meipass",
    )

    assert data == tmp_path / "portable-data"
    assert resources == tmp_path / "resources"


def test_macos_frozen_resources_prefer_the_resources_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = tmp_path / "OpenTalos.app" / "Contents"
    frameworks = contents / "Frameworks"
    resources = contents / "Resources"
    frameworks.mkdir(parents=True)
    resources.mkdir()
    monkeypatch.setattr("apps.runtime_paths.sys.platform", "darwin")

    assert resource_root(
        frozen=True,
        env={},
        meipass=frameworks,
    ) == resources
