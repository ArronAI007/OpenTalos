"""Desktop release information, signed update checks, and staged installation."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from apps.runtime_paths import resource_root, user_data_dir
from release_platform.installer import current_arch, current_platform
from release_platform.updater import UpdateError, UpdateManager
from release_platform.version import app_version

DEFAULT_UPDATE_BASE_URL = (
    "https://github.com/ArronAI007/OpenTalos/releases/latest/download"
)


def create_release_router(
    *,
    data_dir: Path | None = None,
    resources: Path | None = None,
    version: str | None = None,
    platform_name: str | None = None,
    arch: str | None = None,
    environ: Mapping[str, str] | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> APIRouter:
    source = dict(os.environ if environ is None else environ)
    root = Path(resources or resource_root()).resolve()
    data = Path(data_dir or user_data_dir()).resolve()
    release_version = version or app_version()
    target_platform = platform_name or current_platform()
    target_arch = arch or current_arch()
    router = APIRouter(prefix="/api/release", tags=["release"])

    def manager() -> UpdateManager:
        return UpdateManager(
            data,
            app_version=release_version,
            platform_name=target_platform,
            arch=target_arch,
            public_key=_load_public_key(root, source),
            fetcher=fetcher,
        )

    def ensure_configured() -> tuple[UpdateManager, str]:
        manifest_url = _manifest_url(source, target_platform, target_arch)
        try:
            return manager(), manifest_url
        except UpdateError as error:
            raise HTTPException(503, str(error)) from error

    @router.get("/info")
    async def release_info() -> dict:
        update_manager: UpdateManager | None
        update_error: str | None = None
        try:
            _load_public_key(root, source)
            update_manager = manager()
        except UpdateError as error:
            update_manager = None
            update_error = str(error)
        pending = None
        if update_manager is not None:
            try:
                pending = update_manager.pending()
            except UpdateError as error:
                update_error = str(error)
        return {
            "version": release_version,
            "platform": target_platform,
            "arch": target_arch,
            "data_dir": str(data),
            "configured": update_manager is not None,
            "pending": pending,
            "error": update_error,
        }

    @router.post("/update/check")
    async def check_update() -> dict:
        update_manager, manifest_url = ensure_configured()
        try:
            return await run_in_threadpool(update_manager.check_url, manifest_url)
        except UpdateError as error:
            raise HTTPException(502, str(error)) from error

    @router.post("/update/download")
    async def download_update() -> dict:
        update_manager, manifest_url = ensure_configured()
        try:
            update = await run_in_threadpool(
                update_manager.check_url,
                manifest_url,
            )
            if not update["available"]:
                raise HTTPException(409, "no newer update is available")
            return await run_in_threadpool(update_manager.download, update)
        except UpdateError as error:
            raise HTTPException(502, str(error)) from error

    @router.post("/update/install")
    async def install_update() -> dict:
        update_manager, _ = ensure_configured()
        try:
            return update_manager.request_install()
        except UpdateError as error:
            raise HTTPException(409, str(error)) from error

    return router


def _manifest_url(
    environ: Mapping[str, str],
    platform_name: str,
    arch: str,
) -> str:
    override = environ.get("OPENTALOS_UPDATE_MANIFEST_URL", "").strip()
    if override:
        return override
    return (
        f"{DEFAULT_UPDATE_BASE_URL}/"
        f"OpenTalos-update-{platform_name}-{arch}.json"
    )


def _load_public_key(resources: Path, environ: Mapping[str, str]) -> bytes:
    inline = environ.get("OPENTALOS_UPDATE_PUBLIC_KEY", "").strip()
    if inline:
        if inline.startswith("-----BEGIN"):
            return inline.encode("utf-8")
        try:
            return base64.b64decode(inline, validate=True)
        except ValueError as error:
            raise UpdateError("OPENTALOS_UPDATE_PUBLIC_KEY is invalid") from error

    configured = environ.get("OPENTALOS_UPDATE_PUBLIC_KEY_FILE", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(
        (
            resources / "runtime" / "update-public-key.pem",
            resources / "release" / "update-public-key.pem",
        )
    )
    for path in candidates:
        if path.is_file():
            return path.read_bytes()
    raise UpdateError("update signing public key is not configured")
