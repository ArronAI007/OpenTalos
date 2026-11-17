"""HTTP routes for read-only local coding-Agent session history."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from agent_platform.sessions import LocalSessionNotFoundError, LocalSessionService


def create_local_session_router(service: LocalSessionService) -> APIRouter:
    router = APIRouter(prefix="/api/local-sessions", tags=["local-sessions"])

    @router.get("")
    async def sessions(
        source: str | None = None,
        q: str | None = None,
        limit: int = Query(250, ge=1, le=1000),
    ) -> dict:
        return await asyncio.to_thread(
            service.list_sessions,
            source=source,
            query=q,
            limit=limit,
        )

    @router.get("/{source}/{session_id}")
    async def session(source: str, session_id: str) -> dict:
        try:
            return await asyncio.to_thread(service.get_session, source, session_id)
        except LocalSessionNotFoundError as error:
            raise HTTPException(404, "local Agent session not found") from error

    return router


__all__ = ["create_local_session_router"]
