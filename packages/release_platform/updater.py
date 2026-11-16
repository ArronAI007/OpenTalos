"""Signed update manifests, artifact verification, and atomic update staging."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


class UpdateError(RuntimeError):
    pass


def canonical_manifest_payload(manifest: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def verify_manifest_signature(
    manifest: dict[str, Any],
    public_key: bytes,
) -> bool:
    signature = manifest.get("signature")
    if not isinstance(signature, str) or not signature:
        raise UpdateError("update manifest signature is missing")
    try:
        key = (
            Ed25519PublicKey.from_public_bytes(public_key)
            if len(public_key) == 32
            else load_pem_public_key(public_key)
        )
        key.verify(
            base64.b64decode(signature),
            canonical_manifest_payload(manifest),
        )
    except (ValueError, InvalidSignature, TypeError) as error:
        raise UpdateError("update manifest signature is invalid") from error
    return True


class UpdateManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        app_version: str,
        platform_name: str,
        arch: str,
        public_key: bytes,
        fetcher: Callable[[str], bytes] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.app_version = app_version
        self.platform_name = platform_name
        self.arch = arch
        self.public_key = public_key
        self.fetcher = fetcher or _fetch
        self.update_dir = self.data_dir / "updates"
        self.pending_path = self.update_dir / "pending.json"
        self.install_request_path = self.update_dir / "install-request.json"

    def load_manifest(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UpdateError(f"cannot read update manifest: {error}") from error
        return self.load_manifest_dict(payload)

    def load_manifest_dict(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            raise UpdateError("update manifest must be a JSON object")
        verify_manifest_signature(manifest, self.public_key)
        if manifest.get("platform") != self.platform_name:
            raise UpdateError("update manifest platform does not match this app")
        if manifest.get("arch") not in {self.arch, "universal"}:
            raise UpdateError("update manifest architecture does not match this app")
        for field in ("version", "url", "sha256", "size"):
            if field not in manifest:
                raise UpdateError(f"update manifest is missing {field}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(manifest["sha256"])):
            raise UpdateError("update manifest sha256 is invalid")
        if not isinstance(manifest["size"], int) or manifest["size"] <= 0:
            raise UpdateError("update manifest size is invalid")
        if not str(manifest["url"]).startswith(("https://", "http://127.0.0.1")):
            raise UpdateError("update manifest URL must use HTTPS")
        minimum_version = str(manifest.get("minimum_version", "0.0.0"))
        if _version_key(self.app_version) < _version_key(minimum_version):
            raise UpdateError(
                f"update requires OpenTalos {minimum_version} or newer"
            )
        available = _version_key(str(manifest["version"])) > _version_key(self.app_version)
        return {
            "available": available,
            "current_version": self.app_version,
            "manifest": manifest,
        }

    def check_url(self, url: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.fetcher(url).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise UpdateError(f"cannot decode update manifest: {error}") from error
        return self.load_manifest_dict(payload)

    def stage(
        self,
        update: dict[str, Any],
        artifact_path: Path,
    ) -> dict[str, Any]:
        if not update.get("available"):
            raise UpdateError("update is not newer than this application")
        manifest = update["manifest"]
        artifact = Path(artifact_path)
        try:
            content = artifact.read_bytes()
        except OSError as error:
            raise UpdateError(f"cannot read update artifact: {error}") from error
        return self.stage_bytes(update, content)

    def download(self, update: dict[str, Any]) -> dict[str, Any]:
        if not update.get("available"):
            raise UpdateError("update is not newer than this application")
        manifest = update["manifest"]
        try:
            content = self.fetcher(str(manifest["url"]))
        except OSError as error:
            raise UpdateError(f"cannot download update artifact: {error}") from error
        return self.stage_bytes(update, content)

    def stage_bytes(
        self,
        update: dict[str, Any],
        content: bytes,
    ) -> dict[str, Any]:
        if not update.get("available"):
            raise UpdateError("update is not newer than this application")
        manifest = update["manifest"]
        if len(content) != int(manifest["size"]):
            raise UpdateError("update artifact size does not match manifest")
        if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
            raise UpdateError("update artifact checksum does not match manifest")

        version = str(manifest["version"])
        target_dir = self.update_dir / version
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / _artifact_name(str(manifest["url"]))
        _atomic_bytes(target, content)
        pending = {
            "version": version,
            "artifact_path": str(target),
            "sha256": manifest["sha256"],
            "signature": manifest["signature"],
            "platform": manifest["platform"],
            "arch": manifest["arch"],
            "staged_at": _now(),
        }
        _atomic_bytes(
            self.pending_path,
            (json.dumps(pending, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return pending

    def pending(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise UpdateError(f"cannot read pending update: {error}") from error
        if not isinstance(payload, dict):
            raise UpdateError("pending update must be a JSON object")
        artifact = Path(str(payload.get("artifact_path", "")))
        if not artifact.is_file():
            raise UpdateError("pending update artifact is missing")
        return payload

    def request_install(self) -> dict[str, Any]:
        pending = self.pending()
        if pending is None:
            raise UpdateError("no update has been staged")
        request = {
            **pending,
            "requested_at": _now(),
        }
        _atomic_bytes(
            self.install_request_path,
            (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return request


def _version_key(version: str) -> tuple[int, ...]:
    clean = version.lstrip("v").split("-", 1)[0]
    try:
        parts = tuple(int(part) for part in clean.split("."))
    except ValueError as error:
        raise UpdateError(f"invalid semantic version: {version}") from error
    return parts + (0,) * (4 - len(parts))


def _artifact_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return "update.bin"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _fetch(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
