"""Minimal MCP stdio server exposing image and video generation tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from apps.runtime_paths import user_data_dir

from .backends import OpenAIImageBackend
from .service import GeneratedMedia, MediaGenerationService, MediaStore


class MockImageBackend:
    async def generate(self, prompt: str, *, size: str) -> GeneratedMedia:
        return GeneratedMedia(b"mock-image", "image/png", "png")


class MockVideoBackend:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    async def start(self, prompt: str) -> str:
        job_id = f"mock-video-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"status": "running", "progress": 0.2}
        return job_id

    async def status(self, job_id: str) -> dict:
        self.jobs[job_id]["progress"] = min(
            1.0, self.jobs[job_id]["progress"] + 0.1
        )
        return {"id": job_id, **self.jobs[job_id]}

    async def cancel(self, job_id: str) -> dict:
        self.jobs[job_id]["status"] = "cancelled"
        return {"id": job_id, **self.jobs[job_id]}


def _service() -> MediaGenerationService:
    data_dir = user_data_dir()
    database = Path(os.environ.get("OPENTALOS_DB_PATH", data_dir / "chat.db"))
    root = Path(os.environ.get("OPENTALOS_MEDIA_ROOT", data_dir / "media"))
    if os.environ.get("OPENTALOS_MEDIA_MOCK") == "1":
        image = MockImageBackend()
        video = MockVideoBackend()
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        image = OpenAIImageBackend(api_key) if api_key else None
        video = None
    return MediaGenerationService(
        MediaStore(database, root),
        image_backend=image,
        video_backend=video,
    )


SERVICE = _service()

_TOOLS = [
    {
        "name": "generate_image",
        "description": "Generate a persisted image from a prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "generate_video",
        "description": "Start, inspect, or cancel a video generation job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "status", "cancel"]},
                "prompt": {"type": "string"},
                "job_id": {"type": "string"},
            },
            "required": ["action"],
        },
    },
]


async def call_tool(name: str, arguments: dict) -> dict:
    if name == "generate_image":
        result = await SERVICE.generate_image(
            arguments["prompt"],
            size=arguments.get("size", "1024x1024"),
        )
    elif name == "generate_video":
        action = arguments["action"]
        if action == "start":
            result = await SERVICE.start_video(arguments["prompt"])
        elif action == "status":
            result = await SERVICE.video_status(arguments["job_id"])
        elif action == "cancel":
            result = await SERVICE.cancel_video(arguments["job_id"])
        else:
            raise ValueError("unsupported video action")
    else:
        raise ValueError(f"unknown tool: {name}")
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ],
        "isError": False,
    }


async def serve() -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in request:
            continue
        method = request.get("method")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "opentalos-media", "version": "0.1.0"},
                }
            elif method == "tools/list":
                result = {"tools": _TOOLS}
            elif method == "tools/call":
                params = request.get("params") or {}
                result = await call_tool(params.get("name"), params.get("arguments") or {})
            elif method == "ping":
                result = {}
            else:
                raise ValueError(f"unknown method: {method}")
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32000, "message": str(error)},
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
