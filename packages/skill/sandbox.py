"""可选的 Docker 沙箱：把技能脚本放进一次性容器执行。

默认关闭（execution.execute_script 在 SANDBOX_MODE != "docker" 时走宿主机直跑）。开启后
用 docker-py 起容器，安全边界对齐旧 TS 版 packages/sandbox：无网络（network_mode="none"）、
非 root 用户、内存/CPU 配额、nproc ulimit、/scratch 16MB tmpfs、脚本只读挂载。

执行与超时赛跑：docker-py 的 exec_run 是同步阻塞、不支持超时，用 run_in_executor + wait_for
包一层；真正让脚本停下来的是 finally 里无条件执行的 container.stop()（强制杀容器），跟旧实现
一致——赛跑超时只是"不再等"。镜像由 SANDBOX_IMAGE 配置（需自带 python3；默认镜像同时带
python3 与 node，兼容 .py/.js/.mjs/.cjs）；容器内用户由 SANDBOX_USER 配置。
"""

import asyncio
import os
from pathlib import Path

from .execution import ScriptResult, resolve_interpreter

DEFAULT_IMAGE = "nikolaik/python-nodejs:python3.12-nodejs22"
DEFAULT_USER = "pn"
MEM_LIMIT = "256m"
NANO_CPUS = 500_000_000
NPROC = 64
SCRATCH = "/scratch"
INPUT_PATH = f"{SCRATCH}/input.txt"
MAX_INPUT_BYTES = 65536

# 容器内解释器命令（镜像自带，走 PATH）；与 execution.INTERPRETER_BY_EXTENSION 支持的扩展名一一对应。
_CONTAINER_INTERPRETER = {".py": "python3", ".js": "node", ".mjs": "node", ".cjs": "node"}


def _environment() -> tuple[str, str]:
    return (
        os.environ.get("SANDBOX_IMAGE") or DEFAULT_IMAGE,
        os.environ.get("SANDBOX_USER") or DEFAULT_USER,
    )


def build_container(script_path: Path):
    """起一个占位容器（tail -f /dev/null），脚本随后用 exec_run 在里面跑。"""
    import docker  # type: ignore[import-not-found]
    from docker.types import Ulimit  # type: ignore[import-not-found]

    image, user = _environment()
    client = docker.from_env()
    return client.containers.run(
        image,
        command=["tail", "-f", "/dev/null"],
        detach=True,
        auto_remove=True,
        network_mode="none",
        user=user,
        mem_limit=MEM_LIMIT,
        nano_cpus=NANO_CPUS,
        ulimits=[Ulimit(name="nproc", soft=NPROC, hard=NPROC)],
        tmpfs={SCRATCH: "rw,size=16m,mode=1777"},
        volumes={str(script_path): {"bind": f"/sandbox/{script_path.name}", "mode": "ro"}},
        working_dir=SCRATCH,
    )


def _exec_script(container, interpreter: str, filename: str, args: list[str], input_text: str | None):
    if input_text is not None:
        # 不用 docker cp（对 tmpfs 挂载点静默 no-op）；与旧实现一致，用 exec + 环境变量写文件。
        container.exec_run(
            ["sh", "-c", f'printf %s "$SANDBOX_INPUT_TEXT" > {INPUT_PATH}'],
            environment={"SANDBOX_INPUT_TEXT": input_text},
        )
    return container.exec_run([interpreter, f"/sandbox/{filename}", *args], demux=True)


def _stop_container(container) -> None:
    try:
        container.stop(timeout=1)
    except Exception:  # noqa: BLE001 - auto_remove 可能已移除；停止失败不影响结果
        pass


async def run_in_sandbox(
    script_path: Path,
    args: list[str],
    input_text: str | None,
    timeout_ms: int,
) -> ScriptResult:
    if input_text is not None and len(input_text.encode("utf-8")) > MAX_INPUT_BYTES:
        return ScriptResult(stdout="", stderr="input_text too large", exit_code=-1, timed_out=False)

    resolve_interpreter(script_path)  # 校验扩展名（不支持的抛 PathValidationError）
    interpreter = _CONTAINER_INTERPRETER[script_path.suffix]
    container = await asyncio.to_thread(build_container, script_path)
    try:
        loop = asyncio.get_running_loop()
        try:
            exit_code, streams = await asyncio.wait_for(
                loop.run_in_executor(None, _exec_script, container, interpreter, script_path.name, args, input_text),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            return ScriptResult(stdout="", stderr="", exit_code=-1, timed_out=True)
        stdout_bytes, stderr_bytes = streams if streams else (b"", b"")
        return ScriptResult(
            stdout=(stdout_bytes or b"").decode("utf-8", errors="replace"),
            stderr=(stderr_bytes or b"").decode("utf-8", errors="replace"),
            exit_code=exit_code if exit_code is not None else -1,
            timed_out=False,
        )
    finally:
        # 无论是正常结束还是超时（exec 线程仍在跑），都强制停容器让脚本真正终止。
        await asyncio.to_thread(_stop_container, container)
