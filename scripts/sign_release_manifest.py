#!/usr/bin/env python3
"""Create, sign, and verify OpenTalos Ed25519 update manifests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from release_platform.updater import (
    canonical_manifest_payload,
    verify_manifest_signature,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-key-dir", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--platform", choices=("darwin", "win32", "linux"))
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--url")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--minimum-version", default="0.1.0")
    parser.add_argument("--published-at", default=None)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--private-key-env")
    parser.add_argument("--derive-public-key-env")
    parser.add_argument("--public-key-out", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--public-key", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.generate_key_dir:
        return _generate_key(args.generate_key_dir)
    if args.derive_public_key_env:
        if not args.public_key_out:
            raise SystemExit("--public-key-out is required with --derive-public-key-env")
        return _derive_public_key(args.derive_public_key_env, args.public_key_out)
    if args.verify:
        if not args.public_key:
            raise SystemExit("--public-key is required with --verify")
        manifest = json.loads(args.verify.read_text(encoding="utf-8"))
        verify_manifest_signature(
            manifest,
            args.public_key.read_bytes(),
        )
        print(f"verified: {args.verify}")
        return 0
    required = {
        "--artifact": args.artifact,
        "--version": args.version,
        "--platform": args.platform,
        "--url": args.url,
        "--output": args.output,
    }
    missing = [name for name, value in required.items() if value is None]
    if args.private_key is None and not args.private_key_env:
        missing.append("--private-key or --private-key-env")
    if missing:
        raise SystemExit(f"missing required arguments: {', '.join(missing)}")

    artifact = args.artifact.resolve()
    hasher = hashlib.sha256()
    size = 0
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
            size += len(chunk)
    manifest = {
        "schema": 1,
        "channel": args.channel,
        "version": args.version.lstrip("v"),
        "platform": args.platform,
        "arch": args.arch,
        "minimum_version": args.minimum_version,
        "url": args.url,
        "sha256": hasher.hexdigest(),
        "size": size,
        "published_at": args.published_at or _now(),
    }
    private_key = serialization.load_pem_private_key(
        _private_key_bytes(args),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SystemExit("--private-key must contain an Ed25519 private key")
    manifest["signature"] = base64.b64encode(
        private_key.sign(canonical_manifest_payload(manifest))
    ).decode("ascii")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.checksums:
        args.checksums.write_text(
            f"{manifest['sha256']}  {artifact.name}\n",
            encoding="utf-8",
        )
    print(f"manifest: {args.output}")
    return 0


def _generate_key(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory / "update-private-key.pem"
    public_path = directory / "update-public-key.pem"
    if private_path.exists() or public_path.exists():
        raise SystemExit(f"refusing to overwrite existing keys in {directory}")
    private_key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(private_path, 0o600)
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"private key: {private_path}")
    print(f"public key: {public_path}")
    return 0


def _private_key_bytes(args: argparse.Namespace) -> bytes:
    if args.private_key is not None:
        return args.private_key.read_bytes()
    value = os.environ.get(str(args.private_key_env), "").strip()
    if not value:
        raise SystemExit(f"environment variable {args.private_key_env} is empty")
    if value.startswith("-----BEGIN"):
        return value.encode("utf-8")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise SystemExit(
            f"environment variable {args.private_key_env} is not valid base64 PEM"
        ) from error


def _derive_public_key(env_name: str, output: Path) -> int:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise SystemExit(f"environment variable {env_name} is empty")
    content = (
        value.encode("utf-8")
        if value.startswith("-----BEGIN")
        else base64.b64decode(value, validate=True)
    )
    private_key = serialization.load_pem_private_key(content, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SystemExit(f"{env_name} must contain an Ed25519 private key")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"public key: {output}")
    return 0


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


if __name__ == "__main__":
    raise SystemExit(main())
