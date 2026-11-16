import json
import os
import sys
from pathlib import Path

import pytest

from mcp.client import MCPClient, MCPServerConfig


@pytest.mark.asyncio
async def test_media_mcp_server_lists_and_calls_tools(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "packages"),
        "OPENTALOS_DB_PATH": str(tmp_path / "chat.db"),
        "OPENTALOS_MEDIA_ROOT": str(tmp_path / "media"),
        "OPENTALOS_MEDIA_MOCK": "1",
    }
    client = MCPClient(
        MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            args=["-m", "media_platform.mcp_server"],
            env=env,
        )
    )
    await client.connect()
    try:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} >= {"generate_image", "generate_video"}
        result = await client.call_tool(
            "generate_image",
            {"prompt": "a cat", "size": "512x512"},
        )
        text = result.content[0].text
        payload = json.loads(text)
        assert payload["status"] == "completed"
        assert Path(payload["path"]).read_bytes() == b"mock-image"
    finally:
        await client.close()
