from pathlib import Path

import pytest

from media_platform.service import (
    GeneratedMedia,
    MediaGenerationService,
    MediaStore,
)
from media_platform.tools import ImageGenerationTool, VideoGenerationTool


class ImageBackend:
    async def generate(self, prompt: str, *, size: str) -> GeneratedMedia:
        assert prompt == "a cat"
        return GeneratedMedia(data=b"png-bytes", mime_type="image/png", extension="png")


class VideoBackend:
    def __init__(self) -> None:
        self.status_value = "running"
        self.cancelled = False

    async def start(self, prompt: str) -> str:
        assert prompt == "a moving cat"
        return "video-job-1"

    async def status(self, job_id: str) -> dict:
        return {"id": job_id, "status": self.status_value, "progress": 0.5}

    async def cancel(self, job_id: str) -> dict:
        self.status_value = "cancelled"
        self.cancelled = True
        return {"id": job_id, "status": "cancelled"}


@pytest.mark.asyncio
async def test_image_generation_persists_media_reference(tmp_path: Path) -> None:
    store = MediaStore(tmp_path / "media.db", tmp_path / "media")
    service = MediaGenerationService(store, image_backend=ImageBackend())

    result = await service.generate_image("a cat", size="1024x1024")

    assert result["mime_type"] == "image/png"
    assert result["path"].endswith(".png")
    assert Path(result["path"]).read_bytes() == b"png-bytes"
    assert store.get_job(result["job_id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_video_generation_progress_and_cancel(tmp_path: Path) -> None:
    backend = VideoBackend()
    store = MediaStore(tmp_path / "media.db", tmp_path / "media")
    service = MediaGenerationService(store, video_backend=backend)

    started = await service.start_video("a moving cat")
    status = await service.video_status(started["job_id"])
    cancelled = await service.cancel_video(started["job_id"])

    assert status["progress"] == 0.5
    assert cancelled["status"] == "cancelled"
    assert backend.cancelled is True


@pytest.mark.asyncio
async def test_media_tools_expose_agent_tools(tmp_path: Path) -> None:
    store = MediaStore(tmp_path / "media.db", tmp_path / "media")
    service = MediaGenerationService(
        store,
        image_backend=ImageBackend(),
        video_backend=VideoBackend(),
    )

    image = await ImageGenerationTool(service).acall(
        {"prompt": "a cat", "size": "1024x1024"}
    )
    video = await VideoGenerationTool(service).acall(
        {"action": "start", "prompt": "a moving cat"}
    )

    assert image.succeeded is True
    assert "image/png" in image.output
    assert video.succeeded is True
    assert "video-job-1" in video.output
