"""HTTP control plane for M7 privacy, sharing, subscriptions, tools, and media."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from gateway_access.store import GatewayAccessDeniedError, GatewayAccessStore
from media_platform.service import MediaGenerationService
from plugin_platform.manifest import PluginValidationError
from plugin_platform.store import PluginIntegrityError, PluginStore
from privacy.engine import PrivacyBlockedError, PrivacyEngine, PrivacyUnavailableError
from privacy.store import PrivacyRule, PrivacyStore
from subscriptions.service import SubscriptionInventory, SubscriptionValidationError
from websearch.fetch import WebFetchError, WebFetchService
from websearch.key_rotation import SearchKeyStore


class PrivacySettingsBody(BaseModel):
    enabled: bool | None = None
    fail_closed: bool | None = None
    placeholder_ttl_seconds: int | None = Field(default=None, ge=1)


class PrivacyRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    title: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    action: Literal["mask", "warn", "block"] = "mask"
    category: str = "custom"


class PrivacyTestBody(BaseModel):
    text: str
    scope: str = "test"


class GatewayKeyBody(BaseModel):
    name: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=lambda: ["chat.read"])
    allowed_models: list[str] = Field(default_factory=list)
    allowed_accounts: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    read_only: bool = False
    admin: bool = False
    daily_requests: int | None = Field(default=None, ge=0)
    weekly_requests: int | None = Field(default=None, ge=0)
    monthly_requests: int | None = Field(default=None, ge=0)
    token_limit: int | None = Field(default=None, ge=0)
    cost_limit_micros: int | None = Field(default=None, ge=0)
    cache_limit: int | None = Field(default=None, ge=0)
    concurrency_limit: int | None = Field(default=None, ge=0)


class GatewayKeyUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    scopes: list[str] | None = None
    allowed_models: list[str] | None = None
    allowed_accounts: list[str] | None = None
    allowed_groups: list[str] | None = None


class SharingConfigBody(BaseModel):
    enabled: bool | None = None
    bind_host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    exposure_warning_acknowledged: bool | None = None
    tls_mode: Literal["off", "custom", "mtls"] | None = None
    cert_file: str | None = None
    key_file: str | None = None
    ca_file: str | None = None
    require_client_cert: bool | None = None


class WarmupBody(BaseModel):
    account_id: str
    mode: Literal["daily", "reset"] = "daily"
    at_time: str = "08:00"


class SubscriptionExportBody(BaseModel):
    include_credentials: bool = False
    acknowledge_credentials: bool = False


class SubscriptionImportBody(BaseModel):
    payload: dict


class SearchKeyBody(BaseModel):
    provider: str = "tavily"
    name: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    priority: int = 0


class SearchKeyUpdateBody(BaseModel):
    enabled: bool


class PluginInstallBody(BaseModel):
    source: str
    allow_update: bool = False


class PluginDiscoverBody(BaseModel):
    repository: str


class PluginToggleBody(BaseModel):
    enabled: bool


class WebFetchBody(BaseModel):
    url: str
    scope: str = "web-fetch"


class ImageGenerationBody(BaseModel):
    prompt: str = Field(min_length=1)
    size: str = "1024x1024"


class VideoGenerationBody(BaseModel):
    prompt: str = Field(min_length=1)


def create_m7_router(
    *,
    privacy_store: PrivacyStore,
    privacy_engine: PrivacyEngine,
    access_store: GatewayAccessStore,
    subscriptions: SubscriptionInventory,
    search_keys: SearchKeyStore,
    plugins: PluginStore,
    media: MediaGenerationService,
    web_fetch: WebFetchService,
) -> APIRouter:
    router = APIRouter(prefix="/api/m7", tags=["m7"])

    @router.get("/privacy/settings")
    async def privacy_settings() -> dict:
        return privacy_store.get_settings()

    @router.patch("/privacy/settings")
    async def update_privacy_settings(body: PrivacySettingsBody) -> dict:
        try:
            return privacy_store.update_settings(**body.model_dump(exclude_unset=True))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/privacy/rules")
    async def privacy_rules() -> dict:
        return {"rules": [rule.__dict__ for rule in privacy_store.list_rules()]}

    @router.post("/privacy/rules", status_code=201)
    async def save_privacy_rule(body: PrivacyRuleBody) -> dict:
        try:
            rule = privacy_store.save_rule(
                PrivacyRule(
                    id=body.id,
                    title=body.title,
                    pattern=body.pattern,
                    action=body.action,
                    category=body.category,
                )
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return rule.__dict__

    @router.delete("/privacy/rules/{rule_id}", status_code=204)
    async def delete_privacy_rule(rule_id: str) -> None:
        try:
            deleted = privacy_store.delete_rule(rule_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if not deleted:
            raise HTTPException(404, "privacy rule not found")

    @router.post("/privacy/test")
    async def test_privacy(body: PrivacyTestBody) -> dict:
        try:
            result = privacy_engine.mask_text(body.text, scope=body.scope)
        except PrivacyBlockedError as error:
            raise HTTPException(error.status_code, str(error)) from error
        except PrivacyUnavailableError as error:
            raise HTTPException(error.status_code, str(error)) from error
        return {
            "text": result.text,
            "matches": result.matches,
            "warnings": result.warnings,
        }

    @router.get("/privacy/audit")
    async def privacy_audit(limit: int = Query(100, ge=1, le=500)) -> dict:
        return {"audit": privacy_store.list_audit(limit)}

    @router.get("/sharing/config")
    async def sharing_config() -> dict:
        return access_store.get_sharing()

    @router.put("/sharing/config")
    async def update_sharing_config(body: SharingConfigBody) -> dict:
        try:
            return access_store.update_sharing(**body.model_dump(exclude_unset=True))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/sharing/keys")
    async def sharing_keys() -> dict:
        return {"keys": access_store.list_keys()}

    @router.post("/sharing/keys", status_code=201)
    async def create_sharing_key(body: GatewayKeyBody) -> dict:
        try:
            return access_store.create_key(**body.model_dump())
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/sharing/keys/{key_id}")
    async def update_sharing_key(key_id: str, body: GatewayKeyUpdateBody) -> dict:
        try:
            return access_store.update_key(
                key_id,
                **body.model_dump(exclude_unset=True),
            )
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/sharing/keys/{key_id}/rotate")
    async def rotate_sharing_key(key_id: str) -> dict:
        try:
            return access_store.rotate_key(key_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.delete("/sharing/keys/{key_id}", status_code=204)
    async def revoke_sharing_key(key_id: str) -> None:
        if not access_store.revoke_key(key_id):
            raise HTTPException(404, "Gateway key not found")

    @router.get("/sharing/keys/{key_id}/usage")
    async def sharing_key_usage(key_id: str) -> dict:
        return access_store.usage(key_id)

    @router.get("/sharing/audit")
    async def sharing_audit(limit: int = Query(100, ge=1, le=500)) -> dict:
        return {"audit": access_store.list_audit(limit)}

    @router.post("/subscriptions/discover")
    async def discover_subscriptions() -> dict:
        return {"accounts": subscriptions.discover()}

    @router.get("/subscriptions")
    async def list_subscriptions() -> dict:
        return {"accounts": subscriptions.store.list_accounts()}

    @router.post("/subscriptions/{account_id}/refresh")
    async def refresh_subscription(account_id: str) -> dict:
        try:
            return subscriptions.refresh(account_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/subscriptions/export")
    async def export_subscriptions(body: SubscriptionExportBody) -> dict:
        try:
            return subscriptions.export_bundle(**body.model_dump())
        except SubscriptionValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/subscriptions/import")
    async def import_subscriptions(body: SubscriptionImportBody) -> dict:
        try:
            return {"imported": subscriptions.import_bundle(body.payload)}
        except SubscriptionValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/subscriptions/warmups")
    async def warmups() -> dict:
        return {"warmups": subscriptions.store.list_warmups()}

    @router.post("/subscriptions/warmups", status_code=201)
    async def create_warmup(body: WarmupBody) -> dict:
        try:
            return subscriptions.schedule_warmup(
                body.account_id,
                mode=body.mode,
                at_time=body.at_time,
            )
        except SubscriptionValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/subscriptions/warmups/run")
    async def run_warmups() -> dict:
        async def refresh_warmup(account):
            subscriptions.refresh(account["id"])

        return {
            "ran": await subscriptions.run_due_warmups(warm=refresh_warmup)
        }

    @router.get("/tools/search-keys")
    async def search_keys_list() -> dict:
        return {"keys": search_keys.list_keys()}

    @router.post("/tools/search-keys", status_code=201)
    async def search_key_create(body: SearchKeyBody) -> dict:
        try:
            return search_keys.add_key(**body.model_dump())
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/tools/search-keys/{key_id}")
    async def search_key_update(key_id: str, body: SearchKeyUpdateBody) -> dict:
        try:
            return search_keys.set_enabled(key_id, body.enabled)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.delete("/tools/search-keys/{key_id}", status_code=204)
    async def search_key_delete(key_id: str) -> None:
        if not search_keys.delete_key(key_id):
            raise HTTPException(404, "search key not found")

    @router.get("/tools/search-keys/{key_id}/usage")
    async def search_key_usage(key_id: str) -> dict:
        try:
            return search_keys.usage(key_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/tools/web-fetch")
    async def web_fetch_route(body: WebFetchBody) -> dict:
        try:
            return await web_fetch.fetch(body.url, scope=body.scope)
        except WebFetchError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/plugins")
    async def plugins_list(enabled_only: bool = False) -> dict:
        return {"plugins": plugins.list_plugins(enabled_only=enabled_only)}

    @router.post("/plugins/discover")
    async def plugins_discover(body: PluginDiscoverBody) -> dict:
        return {"plugins": plugins.discover(body.repository)}

    @router.post("/plugins/install", status_code=201)
    async def plugin_install(body: PluginInstallBody) -> dict:
        try:
            return plugins.install(body.source, allow_update=body.allow_update)
        except PluginValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/plugins/{plugin_id}")
    async def plugin_toggle(plugin_id: str, body: PluginToggleBody) -> dict:
        try:
            return plugins.set_enabled(plugin_id, body.enabled)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/plugins/{plugin_id}/verify")
    async def plugin_verify(plugin_id: str) -> dict:
        try:
            return plugins.verify(plugin_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        except PluginIntegrityError as error:
            raise HTTPException(409, str(error)) from error

    @router.delete("/plugins/{plugin_id}", status_code=204)
    async def plugin_remove(plugin_id: str) -> None:
        if not plugins.remove(plugin_id):
            raise HTTPException(404, "plugin not found")

    @router.get("/media/jobs")
    async def media_jobs(kind: str | None = None) -> dict:
        return {"jobs": media.store.list_jobs(kind)}

    @router.get("/media/files/{job_id}")
    async def media_file(job_id: str):
        try:
            job = media.store.get_job(job_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        if not job.get("path"):
            raise HTTPException(404, "media file not ready")
        path = Path(job["path"]).resolve()
        root = media.store.media_root.resolve()
        if root not in path.parents:
            raise HTTPException(400, "invalid media path")
        return FileResponse(path, media_type=job.get("mime_type") or "application/octet-stream")

    @router.post("/media/images", status_code=201)
    async def generate_image(body: ImageGenerationBody) -> dict:
        try:
            return await media.generate_image(body.prompt, size=body.size)
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.post("/media/videos", status_code=202)
    async def generate_video(body: VideoGenerationBody) -> dict:
        try:
            return await media.start_video(body.prompt)
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.get("/media/videos/{job_id}")
    async def video_status(job_id: str) -> dict:
        try:
            return await media.video_status(job_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.delete("/media/videos/{job_id}", status_code=200)
    async def cancel_video(job_id: str) -> dict:
        try:
            return await media.cancel_video(job_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    return router


__all__ = ["create_m7_router"]
