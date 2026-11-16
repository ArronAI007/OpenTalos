"""HTTP routes for provider accounts, model discovery, and control-plane profiles."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from model_platform.control_plane import (
    ControlPlaneStore,
    ControlPlaneValidationError,
)
from model_platform.discovery import ModelDiscovery
from model_platform.presets import list_presets


class CreateAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    backend: Literal["openai-compatible", "anthropic", "mock"]
    base_url: str | None = None
    api_key: str = Field(min_length=1)
    proxy_url: str | None = None


class UpdateAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    proxy_url: str | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class SaveProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    payload: dict


def create_model_control_router(
    store: ControlPlaneStore,
    discovery: ModelDiscovery | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/model-control", tags=["model-control"])
    model_discovery = discovery or ModelDiscovery()

    @router.get("/presets")
    async def presets() -> dict:
        return {"presets": [preset.to_dict() for preset in list_presets()]}

    @router.get("/accounts")
    async def list_accounts() -> dict:
        return {"accounts": store.list_accounts()}

    @router.post("/accounts", status_code=201)
    async def create_account(body: CreateAccountBody) -> dict:
        try:
            return store.create_account(**body.model_dump())
        except ControlPlaneValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/accounts/{account_id}")
    async def update_account(account_id: str, body: UpdateAccountBody) -> dict:
        try:
            account = store.update_account(
                account_id,
                **body.model_dump(exclude_unset=True),
            )
        except ControlPlaneValidationError as error:
            raise HTTPException(400, str(error)) from error
        if account is None:
            raise HTTPException(404, "account not found")
        return account

    @router.delete("/accounts/{account_id}", status_code=204)
    async def delete_account(account_id: str) -> None:
        if not store.delete_account(account_id):
            raise HTTPException(404, "account not found")

    @router.post("/accounts/{account_id}/discover")
    async def discover_models(account_id: str) -> dict:
        account = store.get_account_secret(account_id)
        if account is None:
            raise HTTPException(404, "account not found")
        try:
            descriptors = await model_discovery.discover(account)
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from error
        return {"models": store.replace_models(account_id, descriptors)}

    @router.get("/models")
    async def list_models(account_id: str | None = None, q: str | None = None) -> dict:
        return {"models": store.list_models(account_id=account_id, query=q)}

    @router.post("/imports/legacy")
    async def import_legacy() -> dict:
        return {"imported": store.import_legacy_configs(store.list_legacy_configs())}

    @router.get("/profiles")
    async def list_profiles() -> dict:
        return {"profiles": store.list_profiles()}

    @router.post("/profiles", status_code=201)
    async def save_profile(body: SaveProfileBody) -> dict:
        try:
            return store.save_profile(body.name, body.payload)
        except ControlPlaneValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/profiles/{profile_id}", status_code=204)
    async def delete_profile(profile_id: str) -> None:
        if not store.delete_profile(profile_id):
            raise HTTPException(404, "profile not found")

    return router
