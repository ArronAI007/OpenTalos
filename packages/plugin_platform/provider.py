"""Command protocol for provider plugins."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from gateway.upstream import GatewayStream


class PluginCommandError(RuntimeError):
    pass


class PluginCommandRunner:
    def __init__(self, plugin_dir: Path, *, timeout_seconds: float = 30.0) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.timeout_seconds = timeout_seconds

    async def run(self, manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        command = list(manifest["entrypoint"])
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "NO_COLOR": "1",
            "OPENTALOS_PLUGIN_ID": manifest["id"],
        }

        def invoke() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                cwd=self.plugin_dir,
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=environment,
                check=False,
            )

        try:
            result = await asyncio.to_thread(invoke)
        except (OSError, subprocess.SubprocessError) as error:
            raise PluginCommandError(str(error)) from error
        if result.returncode != 0:
            raise PluginCommandError(
                f"plugin exited {result.returncode}: {result.stderr[:1000]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PluginCommandError("plugin returned non-JSON output") from error
        if not isinstance(payload, dict):
            raise PluginCommandError("plugin response must be a JSON object")
        return payload


class PluginProviderUpstream:
    def __init__(self, manifest: dict[str, Any], *, runner: PluginCommandRunner) -> None:
        self.manifest = manifest
        self.runner = runner

    async def complete(self, resolved, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.runner.run(
            self.manifest["manifest"],
            {
                "action": "complete",
                "model": resolved.model_id,
                "request": payload,
            },
        )

    async def stream(self, resolved, payload: dict[str, Any]) -> GatewayStream:
        response = await self.complete(resolved, payload)
        content = (
            ((response.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        )

        async def body():
            event = {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content},
                        "finish_reason": "stop",
                    }
                ]
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return GatewayStream(status_code=200, body=body())
