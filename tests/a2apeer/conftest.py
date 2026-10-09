"""tests/a2apeer/ 目录共享的 fixture：起一个真实 demo_server.py 子进程当测试用的 A2A peer。"""
import asyncio
import os
import socket
import sys
from pathlib import Path

import httpx
import pytest

_DEMO_SERVER = str(Path(__file__).resolve().parent.parent.parent / "packages" / "a2apeer" / "demo_server.py")
_PACKAGES_DIR = str(Path(__file__).resolve().parent.parent.parent / "packages")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def demo_peer():
    """真实起一个 demo_server.py 子进程，等 /health 变绿后把 base URL yield 给测试，
    测完无论成败都 terminate 掉。固定脚本化回复 "HELLO FROM PEER"，所有用到这个 fixture
    的测试都认这个值。"""
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": _PACKAGES_DIR}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _DEMO_SERVER, "--port", str(port), "--reply", "HELLO FROM PEER",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=env,
    )
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(30):
            try:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if resp.status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError("demo peer did not become healthy in time")
        yield url
    finally:
        proc.terminate()
        await proc.wait()
