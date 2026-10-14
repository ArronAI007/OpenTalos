"""stdio 传输：asyncio 子进程 + 进程组生命周期管理（对齐 pi `transports/stdio.ts`）。"""
import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys
from typing import Any

from .base import TransportEventsMixin

DEFAULT_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
STDIN_CLOSE_GRACE_MS = 500
DEFAULT_CLOSE_TIMEOUT_MS = 2000
STDERR_RING_BUFFER_BYTES = 64 * 1024

_live_process_groups: set[int] = set()
_exit_hook_installed = False


def _cleanup_live_process_groups() -> None:
    for pgid in list(_live_process_groups):
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass


def _install_exit_hook() -> None:
    global _exit_hook_installed
    if _exit_hook_installed:
        return
    atexit.register(_cleanup_live_process_groups)
    _exit_hook_installed = True


class StdioTransport(TransportEventsMixin):
    def __init__(
        self,
        command: str,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        close_timeout_ms: int = DEFAULT_CLOSE_TIMEOUT_MS,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> None:
        super().__init__()
        self._command = command
        self._args = args
        self._env = env
        self._close_timeout_ms = close_timeout_ms
        self._max_message_bytes = max_message_bytes
        self._process: asyncio.subprocess.Process | None = None
        self._pgid: int | None = None
        self._stderr_buffer = bytearray()
        self._read_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        merged_env = {**os.environ, **self._env} if self._env else None
        kwargs: dict[str, Any] = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            **kwargs,
        )
        if sys.platform != "win32":
            self._pgid = os.getpgid(self._process.pid)
            _live_process_groups.add(self._pgid)
            _install_exit_hook()
        self._read_task = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._read_stderr_loop())

    async def send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("StdioTransport is not started")
        line = (json.dumps(message) + "\n").encode("utf-8")
        self._process.stdin.write(line)
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                try:
                    line = await self._process.stdout.readline()
                except ValueError:
                    await self._emit_error(RuntimeError("a single stdio message exceeded the size limit"))
                    continue
                if not line:
                    break
                if len(line) > self._max_message_bytes:
                    await self._emit_error(RuntimeError("a single stdio message exceeded the size limit"))
                    continue
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    await self._emit_error(exc)
                    continue
                await self._emit_message(message)
        finally:
            await self._emit_close()

    async def _read_stderr_loop(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while True:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    return
                self._stderr_buffer.extend(chunk)
                overflow = len(self._stderr_buffer) - STDERR_RING_BUFFER_BYTES
                if overflow > 0:
                    del self._stderr_buffer[:overflow]
        except Exception:  # noqa: BLE001 — stderr 读取失败不应该影响主消息通路
            return

    def _kill_process_group(self, sig: signal.Signals) -> None:
        if sys.platform == "win32":
            if self._process is not None:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(self._process.pid)],
                    capture_output=True,
                    check=False,
                )
            return
        if self._pgid is None:
            return
        try:
            os.killpg(self._pgid, sig)
        except ProcessLookupError:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is None:
            await self._emit_close()
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except Exception:  # noqa: BLE001
                pass
        if await self._wait_for_exit(STDIN_CLOSE_GRACE_MS / 1000):
            self._forget_process_group()
            await self._emit_close()
            return
        self._kill_process_group(signal.SIGTERM)
        if await self._wait_for_exit(self._close_timeout_ms / 1000):
            self._forget_process_group()
            await self._emit_close()
            return
        self._kill_process_group(signal.SIGKILL)
        await process.wait()
        self._forget_process_group()
        await self._emit_close()

    def _forget_process_group(self) -> None:
        if self._pgid is not None:
            _live_process_groups.discard(self._pgid)

    async def _wait_for_exit(self, timeout_seconds: float) -> bool:
        if self._process is None:
            return True
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout_seconds)
            return True
        except asyncio.TimeoutError:
            return False
