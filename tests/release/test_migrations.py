import json
import sqlite3
from pathlib import Path

import pytest

from release_platform.migrations import (
    DowngradeBlockedError,
    ReleaseMetadataStore,
)


def test_first_launch_records_release_metadata(tmp_path: Path) -> None:
    store = ReleaseMetadataStore(tmp_path)
    metadata = store.prepare(
        app_version="1.2.3",
        schema_version=3,
        platform_name="darwin",
    )

    assert metadata["app_version"] == "1.2.3"
    assert metadata["schema_version"] == 3
    assert json.loads((tmp_path / "release.json").read_text())["schema_version"] == 3


def test_migration_creates_sqlite_backup_before_changing_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chat.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE demo (value TEXT)")
        connection.execute("INSERT INTO demo VALUES ('before')")
    store = ReleaseMetadataStore(tmp_path)
    store.prepare(app_version="1.0.0", schema_version=1, platform_name="linux")

    metadata = store.prepare(
        app_version="1.1.0",
        schema_version=2,
        platform_name="linux",
    )

    backup = Path(metadata["backup_path"])
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM demo").fetchone()[0] == "before"


def test_newer_schema_blocks_older_application(tmp_path: Path) -> None:
    store = ReleaseMetadataStore(tmp_path)
    store.prepare(app_version="2.0.0", schema_version=5, platform_name="darwin")

    with pytest.raises(DowngradeBlockedError, match="newer data schema"):
        store.prepare(
            app_version="1.9.0",
            schema_version=4,
            platform_name="darwin",
        )
