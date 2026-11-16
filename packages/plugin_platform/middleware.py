"""Gateway middleware hooks backed by an integrity-checked plugin."""

from __future__ import annotations

from typing import Any

from .provider import PluginCommandRunner


class PluginMiddleware:
    def __init__(self, manifest: dict[str, Any], *, runner: PluginCommandRunner) -> None:
        self.manifest = manifest
        self.runner = runner

    async def before_request(self, payload, context):
        return await self.runner.run(
            self.manifest["manifest"],
            {
                "action": "before_request",
                "payload": payload,
                "context": context,
            },
        )

    async def on_event(self, event, context):
        return await self.runner.run(
            self.manifest["manifest"],
            {
                "action": "on_event",
                "event": event,
                "context": context,
            },
        )

    async def after_response(self, response, context):
        return await self.runner.run(
            self.manifest["manifest"],
            {
                "action": "after_response",
                "response": response,
                "context": context,
            },
        )
