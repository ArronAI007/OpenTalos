import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from release_platform.updater import (
    UpdateError,
    UpdateManager,
    canonical_manifest_payload,
    verify_manifest_signature,
)


def _signed_manifest(
    private_key: Ed25519PrivateKey,
    *,
    artifact: bytes,
    version: str = "1.2.0",
) -> dict:
    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": version,
        "platform": "darwin",
        "arch": "x86_64",
        "minimum_version": "1.0.0",
        "url": "https://example.test/OpenTalos.dmg",
        "sha256": hashlib.sha256(artifact).hexdigest(),
        "size": len(artifact),
        "published_at": "2026-11-16T00:00:00Z",
    }
    signature = private_key.sign(canonical_manifest_payload(manifest))
    manifest["signature"] = base64.b64encode(signature).decode("ascii")
    return manifest


def test_manifest_signature_and_artifact_checksum_are_verified(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    artifact = b"release-binary"
    manifest = _signed_manifest(private_key, artifact=artifact)
    manifest_path = tmp_path / "manifest.json"
    artifact_path = tmp_path / "artifact.dmg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    artifact_path.write_bytes(artifact)

    manager = UpdateManager(
        tmp_path / "data",
        app_version="1.1.0",
        platform_name="darwin",
        arch="x86_64",
        public_key=public_key,
    )
    update = manager.load_manifest(manifest_path)
    staged = manager.stage(update, artifact_path)

    assert update["available"] is True
    assert verify_manifest_signature(update["manifest"], public_key) is True
    assert Path(staged["artifact_path"]).read_bytes() == artifact
    assert json.loads((tmp_path / "data" / "updates" / "pending.json").read_text())[
        "version"
    ] == "1.2.0"


def test_invalid_signature_and_checksum_are_rejected(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    manifest = _signed_manifest(private_key, artifact=b"ok")
    manifest["version"] = "9.9.9"

    with pytest.raises(UpdateError, match="signature"):
        verify_manifest_signature(manifest, public_key)

    valid = _signed_manifest(private_key, artifact=b"ok")
    manager = UpdateManager(
        tmp_path / "data",
        app_version="1.0.0",
        platform_name="darwin",
        arch="x86_64",
        public_key=public_key,
    )
    loaded = manager.load_manifest_dict(valid)
    bad_artifact = tmp_path / "bad.dmg"
    bad_artifact.write_bytes(b"NO")
    with pytest.raises(UpdateError, match="checksum"):
        manager.stage(loaded, bad_artifact)


def test_update_is_unavailable_when_version_is_not_newer(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    manifest = _signed_manifest(private_key, artifact=b"same", version="1.0.0")
    manager = UpdateManager(
        tmp_path / "data",
        app_version="1.0.0",
        platform_name="darwin",
        arch="x86_64",
        public_key=public_key,
    )

    assert manager.load_manifest_dict(manifest)["available"] is False


def test_update_download_is_verified_and_atomically_staged(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    artifact = b"signed-app-artifact"
    manifest = _signed_manifest(private_key, artifact=artifact)

    def fetch(url: str) -> bytes:
        return artifact if url.endswith("OpenTalos.dmg") else b"unused"

    manager = UpdateManager(
        tmp_path / "data",
        app_version="1.0.0",
        platform_name="darwin",
        arch="x86_64",
        public_key=public_key,
        fetcher=fetch,
    )
    update = manager.load_manifest_dict(manifest)

    pending = manager.download(update)

    assert pending["version"] == "1.2.0"
    assert Path(pending["artifact_path"]).read_bytes() == artifact
    assert manager.request_install()["sha256"] == manifest["sha256"]
    assert manager.install_request_path.is_file()


def test_update_rejects_an_unmet_minimum_version(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    manifest = _signed_manifest(private_key, artifact=b"new")
    manifest["minimum_version"] = "2.0.0"
    manifest["signature"] = base64.b64encode(
        private_key.sign(canonical_manifest_payload(manifest))
    ).decode("ascii")
    manager = UpdateManager(
        tmp_path / "data",
        app_version="1.0.0",
        platform_name="darwin",
        arch="x86_64",
        public_key=public_key,
    )

    with pytest.raises(UpdateError, match="requires"):
        manager.load_manifest_dict(manifest)
