import hashlib
import json
from pathlib import Path

from release_platform.installer import (
    apply_install_request,
    current_arch,
    install_request_path,
)


def test_macos_install_request_launches_helper_after_exit(tmp_path: Path) -> None:
    app = tmp_path / "OpenTalos.app"
    app.mkdir()
    artifact = tmp_path / "OpenTalos.dmg"
    artifact.write_bytes(b"dmg")
    request_path = install_request_path(tmp_path / "data")
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "version": "1.2.0",
                "artifact_path": str(artifact),
                "sha256": hashlib.sha256(b"dmg").hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def process_factory(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        return object()

    applied = apply_install_request(
        data_dir=tmp_path / "data",
        app_dir=app,
        platform_name="darwin",
        process_factory=process_factory,
    )

    assert applied is True
    assert calls[0][0] == "/bin/sh"
    assert not request_path.exists()


def test_current_arch_uses_release_naming(monkeypatch) -> None:
    monkeypatch.setattr("release_platform.installer.platform.machine", lambda: "arm64")

    assert current_arch() == "arm64"
