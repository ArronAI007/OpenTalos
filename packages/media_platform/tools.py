"""Agent tools backed by the media generation service."""

from __future__ import annotations

import json
from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

from .service import MediaGenerationService


class ImageGenerationTool(Tool):
    def __init__(self, service: MediaGenerationService) -> None:
        super().__init__(
            name="generate_image",
            description=(
                "Generate an image from a text prompt and return a persisted local media reference."
            ),
            requires_approval=True,
        )
        self.service = service

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("prompt", "string", "Image description."),
            ToolParameter(
                "size",
                "string",
                "Requested image size.",
                required=False,
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            result = await self.service.generate_image(
                arguments["prompt"],
                size=arguments.get("size", "1024x1024"),
            )
        except Exception as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(json.dumps(result, ensure_ascii=False))


class VideoGenerationTool(Tool):
    def __init__(self, service: MediaGenerationService) -> None:
        super().__init__(
            name="generate_video",
            description=(
                "Start, inspect, or cancel a supported video generation job."
            ),
            requires_approval=True,
        )
        self.service = service

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action",
                "string",
                "Generation action.",
                enum=["start", "status", "cancel"],
            ),
            ToolParameter("prompt", "string", "Video description.", required=False),
            ToolParameter("job_id", "string", "Local media job id.", required=False),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            action = arguments["action"]
            if action == "start":
                result = await self.service.start_video(arguments["prompt"])
            elif action == "status":
                result = await self.service.video_status(arguments["job_id"])
            elif action == "cancel":
                result = await self.service.cancel_video(arguments["job_id"])
            else:
                return ToolOutcome.error(f"unsupported video action: {action}")
        except Exception as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(json.dumps(result, ensure_ascii=False))
