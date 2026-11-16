"""HTTP routes for the cross-Agent platform."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.catalog import AgentCatalogError
from agent_platform.config import AgentConfigError
from agent_platform.service import AgentNotFoundError, AgentPlatformService
from agent_platform.store import AgentPlatformValidationError


class BindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    shortlist: list[str] = Field(default_factory=list)
    routing_preference: str | None = None


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)


class LibraryItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str = Field(min_length=1)
    content: str
    metadata: dict = Field(default_factory=dict)


def create_agent_platform_router(service: AgentPlatformService) -> APIRouter:
    router = APIRouter(prefix="/api/agent-platform", tags=["agent-platform"])

    @router.get("/catalog")
    async def catalog(
        installed_only: bool = False,
        q: str | None = None,
    ) -> dict:
        return {"agents": service.list_agents(installed_only=installed_only, query=q)}

    @router.post("/discover")
    async def discover() -> dict:
        return {"agents": service.refresh_installations()}

    @router.get("/agents")
    async def agents(installed_only: bool = True) -> dict:
        return {"agents": service.list_agents(installed_only=installed_only)}

    @router.get("/agents/{agent_id}")
    async def agent(agent_id: str) -> dict:
        try:
            return service.get_agent(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error

    @router.get("/agents/{agent_id}/models")
    async def models(agent_id: str) -> dict:
        try:
            return {"models": service.model_options(agent_id)}
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error

    @router.patch("/agents/{agent_id}/binding")
    async def update_binding(agent_id: str, body: BindingBody) -> dict:
        try:
            return service.update_binding(
                agent_id,
                model=body.model,
                shortlist=body.shortlist,
                routing_preference=body.routing_preference,
            )
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentPlatformValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/agents/{agent_id}/configuration/preview")
    async def preview_configuration(agent_id: str) -> dict:
        try:
            return service.preview_configuration(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/agents/{agent_id}/configuration/apply")
    async def apply_configuration(agent_id: str) -> dict:
        try:
            return service.apply_configuration(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/agents/{agent_id}/restore")
    async def restore_configuration(agent_id: str) -> dict:
        try:
            return service.restore_configuration(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/agents/{agent_id}/update-plan")
    async def update_plan(agent_id: str) -> dict:
        try:
            return service.update_plan(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error

    @router.post("/agents/{agent_id}/update")
    async def update_agent(agent_id: str, confirm: bool = Query(False)) -> dict:
        if not confirm:
            raise HTTPException(400, "explicit update confirmation is required")
        try:
            return service.execute_update(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentPlatformValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/profiles")
    async def profiles() -> dict:
        return {"profiles": service.store.list_profiles()}

    @router.post("/profiles", status_code=201)
    async def save_profile(body: ProfileBody) -> dict:
        try:
            return service.save_profile(body.name)
        except AgentPlatformValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/profiles/{profile_id}/apply")
    async def apply_profile(profile_id: str) -> dict:
        try:
            return service.apply_profile(profile_id)
        except AgentPlatformValidationError as error:
            raise HTTPException(404, str(error)) from error

    @router.delete("/profiles/{profile_id}", status_code=204)
    async def delete_profile(profile_id: str) -> None:
        if not service.store.delete_profile(profile_id):
            raise HTTPException(404, "profile not found")

    @router.get("/library")
    async def library(kind: str | None = None) -> dict:
        return {"items": service.store.list_library_items(kind)}

    @router.post("/library", status_code=201)
    async def create_library_item(body: LibraryItemBody) -> dict:
        try:
            return service.store.create_library_item(**body.model_dump())
        except AgentPlatformValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/library/{item_id}", status_code=204)
    async def delete_library_item(item_id: str) -> None:
        try:
            deleted = service.delete_library_item(item_id)
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error
        if not deleted:
            raise HTTPException(404, "library item not found")

    @router.post("/agents/{agent_id}/library/{item_id}/apply")
    async def apply_library_item(agent_id: str, item_id: str) -> dict:
        try:
            return service.apply_library_item(agent_id, item_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error
        except AgentPlatformValidationError as error:
            raise HTTPException(404, str(error)) from error

    @router.delete("/agents/{agent_id}/library/{item_id}", status_code=200)
    async def remove_library_item(agent_id: str, item_id: str) -> dict:
        try:
            return service.remove_library_item(agent_id, item_id)
        except AgentNotFoundError as error:
            raise HTTPException(404, "Agent not found") from error
        except AgentConfigError as error:
            raise HTTPException(400, str(error)) from error

    return router


__all__ = ["AgentCatalogError", "create_agent_platform_router"]
