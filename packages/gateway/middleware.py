"""Timeout-isolated Gateway middleware pipeline."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from collections.abc import Sequence
from typing import Any, Protocol


class GatewayMiddleware(Protocol):
    async def before_request(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def on_event(
        self,
        event: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def after_response(
        self,
        response: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]: ...


class GatewayMiddlewarePipeline:
    def __init__(
        self,
        middleware: Sequence[GatewayMiddleware] | None = None,
        *,
        timeout_seconds: float = 2.0,
        fail_open: bool = True,
    ) -> None:
        self.middleware = list(middleware or [])
        self.timeout_seconds = max(0.001, timeout_seconds)
        self.fail_open = fail_open
        self.errors: list[dict[str, Any]] = []

    async def before_request(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._run("before_request", payload, context)

    async def on_event(
        self,
        event: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._run("on_event", event, context)

    async def after_response(
        self,
        response: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._run("after_response", response, context)

    async def _run(
        self,
        hook: str,
        value: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        current = value
        for plugin in self.middleware:
            callback = getattr(plugin, hook, None)
            if callback is None:
                continue
            try:
                transformed = await asyncio.wait_for(
                    callback(current, context),
                    timeout=self.timeout_seconds,
                )
                if not isinstance(transformed, dict):
                    raise TypeError(f"{hook} returned {type(transformed).__name__}, expected dict")
                current = transformed
            except Exception as error:
                self.errors.append(
                    {
                        "hook": hook,
                        "plugin": type(plugin).__name__,
                        "error": str(error),
                    }
                )
                if not self.fail_open:
                    raise
        return current


async def transform_chat_sse(
    source: AsyncIterator[str],
    pipeline: GatewayMiddlewarePipeline,
    context: dict[str, Any],
) -> AsyncIterator[str]:
    buffer = ""
    async for chunk in source:
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            transformed = await _transform_block(block, pipeline, context)
            yield transformed + "\n\n"
    if buffer:
        yield await _transform_block(buffer, pipeline, context)


async def _transform_block(
    block: str,
    pipeline: GatewayMiddlewarePipeline,
    context: dict[str, Any],
) -> str:
    data_lines = [
        line[5:].strip()
        for line in block.splitlines()
        if line.startswith("data:")
    ]
    if not data_lines:
        return block
    raw = "\n".join(data_lines)
    if raw == "[DONE]":
        return block
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return block
    if not isinstance(event, dict):
        return block
    transformed = await pipeline.on_event(event, context)
    return "data: " + json.dumps(
        transformed,
        ensure_ascii=False,
        separators=(",", ":"),
    )
