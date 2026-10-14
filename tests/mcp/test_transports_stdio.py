"""stdio 传输的真机测试：真实启动子进程，核实完整的关闭级联和进程组清理。"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp.transports.stdio import StdioTransport, _cleanup_live_process_groups, _live_process_groups

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_IGNORE_SIGTERM_SCRIPT = str(_FIXTURES / "ignore_sigterm_stdio_server.py")
_SPAWN_GRANDCHILD_SCRIPT = str(_FIXTURES / "spawn_grandchild_stdio_server.py")


def _pids_matching(needle: str) -> list[str]:
    result = subprocess.run(["pgrep", "-f", needle], capture_output=True, text=True, check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


class TestGracefulCloseCascade:
    async def test_close_eventually_kills_a_sigterm_ignoring_process(self) -> None:
        transport = StdioTransport(sys.executable, [_IGNORE_SIGTERM_SCRIPT], close_timeout_ms=300)
        await transport.start()
        pid = transport._process.pid
        assert _pids_matching(_IGNORE_SIGTERM_SCRIPT), "子进程应该已经启动"

        start = time.monotonic()
        await transport.close()
        elapsed = time.monotonic() - start

        # 必须走完 stdin 宽限期 (0.5s) + SIGTERM 等待期 (0.3s，被这次构造参数缩短) 才会到 SIGKILL。
        assert elapsed >= 0.5
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not _pids_matching(_IGNORE_SIGTERM_SCRIPT)


class TestGrandchildCleanup:
    async def test_close_terminates_the_wrapper_and_its_grandchild(self) -> None:
        transport = StdioTransport(sys.executable, [_SPAWN_GRANDCHILD_SCRIPT])
        await transport.start()
        # 给孙进程一点时间真正 spawn 出来。
        import asyncio

        await asyncio.sleep(0.3)
        assert _pids_matching(_SPAWN_GRANDCHILD_SCRIPT), "包装进程应该已经启动"
        assert _pids_matching("mcp-test-grandchild-marker"), "孙进程应该已经启动"

        await transport.close()

        assert not _pids_matching(_SPAWN_GRANDCHILD_SCRIPT)
        assert not _pids_matching("mcp-test-grandchild-marker"), "孙进程不应该残留"


class TestHostExitCleanupHook:
    async def test_cleanup_hook_sigterms_still_live_process_groups(self) -> None:
        import asyncio

        transport = StdioTransport(sys.executable, [_IGNORE_SIGTERM_SCRIPT])
        await transport.start()
        pgid = transport._pgid
        assert pgid in _live_process_groups
        await asyncio.sleep(0.2)  # 给脚本留出时间先装上 SIG_IGN handler，再发信号

        # 模拟宿主进程异常退出（不走正常的 close() 路径）：直接调用清理钩子。
        _cleanup_live_process_groups()

        # ignore_sigterm 脚本会忽略这次 SIGTERM，所以进程本身不会退出，但钩子确实尝试过
        # 发送信号——这里核实的是钩子逻辑本身被触发，不是这个特定脚本的信号处理结果。
        # 用一个会响应 SIGTERM 的普通子进程验证钩子真的能让进程退出。
        normal = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(100)"], start_new_session=True
        )
        normal_pgid = os.getpgid(normal.pid)
        _live_process_groups.add(normal_pgid)
        _cleanup_live_process_groups()
        normal.wait(timeout=2)
        assert normal.returncode is not None

        # 清理掉这次测试自己注册的、忽略 SIGTERM 的那个进程组，避免泄漏到下一个测试。
        os.killpg(pgid, signal.SIGKILL)
        _live_process_groups.discard(pgid)
        _live_process_groups.discard(normal_pgid)
