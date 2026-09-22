import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# .py 用服务进程自己的解释器（sys.executable），不赌 PATH 上有没有 python3；
# JS 技能要求宿主机 PATH 上有 node。
INTERPRETER_BY_EXTENSION = {
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".py": sys.executable,
}


class PathValidationError(ValueError):
    """脚本路径/扩展名校验失败——路由层把这个异常转换成 422，不是 500。"""


@dataclass
class ScriptResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


def resolve_interpreter(script_path: Path) -> tuple[str, str]:
    """解析扩展名对应的解释器。纯函数，不做任何 I/O——调用方必须在起任何子进程之前先调用它，
    让不支持的脚本类型快速失败。"""
    ext = script_path.suffix
    interpreter = INTERPRETER_BY_EXTENSION.get(ext)
    if interpreter is None:
        raise PathValidationError(
            f'Unsupported script type "{ext or "(no extension)"}" for "{script_path.name}". '
            f"Supported extensions: {', '.join(INTERPRETER_BY_EXTENSION)}."
        )
    return interpreter, ext


def resolve_script_path(skill_dir: Path, script_relative_path: str) -> Path:
    """校验 script_relative_path 落在 skill_dir 内部，返回符号链接解析后的真实绝对路径。

    脚本是宿主机直跑的（沙箱后续专门重做），路径穿越防护因此更不能省。三层校验：
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


async def execute_script(
    script_path: Path,
    args: list[str],
    input_text: str | None,
    timeout_ms: int,
) -> ScriptResult:
    """宿主机子进程直跑脚本（沙箱后续专门重做，现阶段只面向本地聊天场景）。

    script_path 必须已经是 resolve_script_path 校验过的真实路径——这个函数不重复校验，
    只负责执行。input_text 通过 stdin 传给脚本；没给 input_text 时 stdin 接 DEVNULL，
    主动读 stdin 的脚本会立即拿到 EOF 而不是挂到超时。
    """
    interpreter, _ = resolve_interpreter(script_path)
    process = await asyncio.create_subprocess_exec(
        interpreter,
        str(script_path),
        *args,
        stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input_text.encode("utf-8") if input_text is not None else None),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()  # 回收进程，避免留下僵尸
        return ScriptResult(stdout="", stderr="", exit_code=-1, timed_out=True)

    return ScriptResult(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=process.returncode if process.returncode is not None else -1,
        timed_out=False,
    )
