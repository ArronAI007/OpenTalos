import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.release_routes import DEFAULT_UPDATE_BASE_URL, create_release_router
from release_platform.updater import canonical_manifest_payload


def test_release_routes_check_download_and_request_install(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    artifact = b"update-package"
    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": "1.1.0",
        "platform": "darwin",
        "arch": "x86_64",
        "minimum_version": "1.0.0",
        "url": "https://updates.example/OpenTalos.dmg",
        "sha256": hashlib.sha256(artifact).hexdigest(),
        "size": len(artifact),
        "published_at": "2026-11-16T00:00:00Z",
    }
    manifest["signature"] = base64.b64encode(
        private_key.sign(canonical_manifest_payload(manifest))
    ).decode("ascii")
    resources = tmp_path / "resources"
    public_key = resources / "runtime" / "update-public-key.pem"
    public_key.parent.mkdir(parents=True)
    public_key.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    def fetch(url: str) -> bytes:
        if url.startswith(DEFAULT_UPDATE_BASE_URL):
            return json.dumps(manifest).encode()
        return artifact

    app = FastAPI()
    app.include_router(
        create_release_router(
            data_dir=tmp_path / "data",
            resources=resources,
            version="1.0.0",
            platform_name="darwin",
            arch="x86_64",
            environ={},
            fetcher=fetch,
        )
    )
    client = TestClient(app)

    info = client.get("/api/release/info")
    update = client.post("/api/release/update/check")
    pending = client.post("/api/release/update/download")
    install = client.post("/api/release/update/install")

    assert info.status_code == 200
    assert info.json()["configured"] is True
    assert update.status_code == 200
    assert update.json()["available"] is True
    assert pending.status_code == 200
    assert Path(pending.json()["artifact_path"]).read_bytes() == artifact
    assert install.status_code == 200
    assert install_request_path(tmp_path / "data").is_file()


def test_release_routes_are_disabled_without_manifest_url(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(
        create_release_router(
            data_dir=tmp_path / "data",
            resources=tmp_path / "resources",
            environ={},
        )
    )
    client = TestClient(app)

    assert client.get("/api/release/info").json()["configured"] is False
    assert client.post("/api/release/update/check").status_code == 503


def install_request_path(data_dir: Path) -> Path:
    return data_dir / "updates" / "install-request.json"
