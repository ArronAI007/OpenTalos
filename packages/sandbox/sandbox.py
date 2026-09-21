import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import docker

IMAGE = "nikolaik/python-nodejs:python3.12-nodejs22"
CONTAINER_SCRIPT_DIR = "/skill"
SANDBOX_INPUT_PATH = "/scratch/input.txt"
MEMORY_LIMIT = "256m"
NANO_CPUS = 500_000_000  # 0.5 核
PIDS_LIMIT = 64

INTERPRETER_BY_EXTENSION = {
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    # python3，不是 python：沙箱镜像（nikolaik/python-nodejs）只保证有 python3 这个二进制。
    ".py": "python3",
}


class PathValidationError(ValueError):
    """脚本路径/扩展名校验失败——路由层把这个异常转换成 422，不是 500。"""


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


def resolve_interpreter(script_path: Path) -> tuple[str, str]:
    """解析扩展名对应的解释器。纯函数，不做任何 I/O——调用方必须在起任何容器之前先调用它，
    让不支持的脚本类型快速失败，不碰 Docker。"""
    ext = script_path.suffix
    interpreter = INTERPRETER_BY_EXTENSION.get(ext)
    if interpreter is None:
        raise PathValidationError(
            f'Unsupported script type "{ext or "(no extension)"}" for "{script_path.name}". '
            f'Supported extensions: {", ".join(INTERPRETER_BY_EXTENSION)}.'
        )
    return interpreter, ext


def resolve_script_path(skill_dir: Path, script_relative_path: str) -> Path:
    """校验 script_relative_path 落在 skill_dir 内部，返回符号链接解析后的真实绝对路径。

    三层校验，对应原 TS 版 run-skill-script-tool.ts 的逻辑：
    1. 绝对路径直接拒绝。
    2. 词法解析后必须以 skill_dir（带结尾分隔符）为前缀——带结尾分隔符是为了防止
       "greeter-evil" 这种同前缀兄弟目录绕过一个天真的 startswith 检查。
    3. 上面这步只是文本匹配，不会跟随符号链接——skill_dir 内部一个名字完全合法（不含 ".."）
       的符号链接可能指向目录外的真实文件。对两侧都做 realpath 解析后再次做前缀检查，防止
       符号链接逃逸。
    """
    candidate = Path(script_relative_path)
    if candidate.is_absolute():
        raise PathValidationError("Invalid script_relative_path: absolute paths are not allowed (path traversal rejected).")

    resolved_path = (skill_dir / candidate).resolve(strict=False)
    skill_dir_str = str(skill_dir)
    skill_dir_with_sep = skill_dir_str if skill_dir_str.endswith(os.sep) else skill_dir_str + os.sep
    if not str(resolved_path).startswith(skill_dir_with_sep):
        raise PathValidationError(
            f'Invalid script_relative_path: "{script_relative_path}" resolves outside the skill directory (path traversal rejected).'
        )

    try:
        real_skill_dir = skill_dir.resolve(strict=True)
        real_resolved_path = resolved_path.resolve(strict=True)
    except OSError as error:
        raise PathValidationError(
            f'Invalid script_relative_path: "{script_relative_path}" does not resolve to a real file ({error}).'
        ) from error

    real_skill_dir_str = str(real_skill_dir)
    real_skill_dir_with_sep = real_skill_dir_str if real_skill_dir_str.endswith(os.sep) else real_skill_dir_str + os.sep
    if not str(real_resolved_path).startswith(real_skill_dir_with_sep):
        raise PathValidationError(
            f'Invalid script_relative_path: "{script_relative_path}" resolves (after following symlinks) outside the skill directory (path traversal rejected).'
        )

    return real_resolved_path


async def run_sandboxed_script(
    client: docker.DockerClient,
    script_path: Path,
    args: list[str],
    input_text: str | None,
    timeout_ms: int,
) -> SandboxResult:
    """script_path 必须已经是 resolve_script_path 校验过的真实路径——这个函数不重复校验，
    只负责起容器执行。因为脚本本来就在这台机器的磁盘上（skill 内容和这个服务同进程管理），
    直接只读挂载真实路径，不需要像独立微服务那样先把脚本内容写进临时文件。"""
    interpreter, ext = resolve_interpreter(script_path)
    container_path = f"{CONTAINER_SCRIPT_DIR}/script{ext}"
    loop = asyncio.get_running_loop()

    container = await loop.run_in_executor(
        None,
        lambda: client.containers.run(
            IMAGE,
            command=["tail", "-f", "/dev/null"],
            detach=True,
            auto_remove=True,
            network_mode="none",
            user="pn",
            mem_limit=MEMORY_LIMIT,
            nano_cpus=NANO_CPUS,
            pids_limit=PIDS_LIMIT,
            volumes={str(script_path): {"bind": container_path, "mode": "ro"}},
            tmpfs={"/scratch": "rw,size=16m"},
        ),
    )
    try:
        if input_text is not None:
            # 不用 docker cp——host 侧的 docker cp 对 tmpfs 挂载点是静默 no-op。改用 exec + 单次
            # exec 的环境变量写入，内容永远不会被拼进 shell 命令字符串本身，天然对引号/换行安全。
            write_exit_code, write_output = await loop.run_in_executor(
                None,
                lambda: container.exec_run(
                    ["sh", "-c", f'printf \'%s\' "$SANDBOX_INPUT_TEXT" > {SANDBOX_INPUT_PATH}'],
                    environment={"SANDBOX_INPUT_TEXT": input_text},
                    demux=True,
                ),
            )
            if write_exit_code != 0:
                stderr_bytes = write_output[1] if write_output else None
                stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
                raise RuntimeError(f"Failed to write sandbox input file: {stderr_text}")

        command = [interpreter, container_path, *args]
        try:
            exit_code, output = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: container.exec_run(command, demux=True)),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            return SandboxResult(stdout="", stderr="", exit_code=-1, timed_out=True)

        stdout_bytes, stderr_bytes = output
        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        return SandboxResult(stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=False)
    finally:
        # 无条件停容器——赛跑超时只是"不再等"，真正让还在容器里跑的脚本停下来的是这一步强制
        # 停容器。auto_remove=True 让容器停止后自动清理，不需要额外调用 remove()。
        await loop.run_in_executor(None, lambda: container.stop(timeout=1))
