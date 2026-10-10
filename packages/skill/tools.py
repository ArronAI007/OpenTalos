"""pi 式技能工具：agent 不再走技能服务，而是像 pi 一样用通用文件/命令工具直接操作技能目录。

- read：按 <available_skills> 里给出的绝对路径读取 SKILL.md 及其引用的支持文件。
- bash：在技能目录里执行命令（跑技能自带脚本），需要人工审批，输出视为不可信。

两者都把可访问路径限制在一组允许的根目录（技能根）内，防止越界读取/执行。bash 无法在
进程层真正沙箱化（后续专门重做），所以额外用 requires_approval 把每次执行交给人工确认。
"""
import asyncio
from collections.abc import Sequence
from pathlib import Path

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

MAX_READ_BYTES = 256 * 1024
DEFAULT_BASH_TIMEOUT_SECONDS = 30.0


class PathOutsideRootsError(ValueError):
    """路径为空、不是绝对路径，或落在所有允许根目录之外。"""


class SkillPaths:
    """把工具的路径访问限制在一组根目录（技能根）内。"""

    def __init__(self, roots: Sequence[Path]) -> None:
        self._roots = [Path(root).resolve() for root in roots]
        if not self._roots:
            raise ValueError("SkillPaths requires at least one root directory")

    @property
    def default_root(self) -> Path:
        return self._roots[0]

    def resolve(self, raw: str, *, must_exist: bool = True) -> Path:
        if not raw or not raw.strip():
            raise PathOutsideRootsError("path must not be empty")
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise PathOutsideRootsError(f'"{raw}" must be an absolute path')
        try:
            resolved = candidate.resolve(strict=must_exist)
        except OSError as error:
            raise PathOutsideRootsError(f'"{raw}" does not resolve to a real path ({error})') from error
        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise PathOutsideRootsError(
            f'"{raw}" is outside the allowed skill directories: {", ".join(str(r) for r in self._roots)}'
        )


class ReadTool(Tool):
    """读取 UTF-8 文本文件；用于加载技能文档（SKILL.md）及其引用的参考文件。"""

    def __init__(self, roots: Sequence[Path]) -> None:
        super().__init__(
            name="read",
            description=(
                "Read a UTF-8 text file and return its contents. Use this to open a skill's SKILL.md "
                "at the absolute <location> advertised in <available_skills>, and any supporting files "
                "it references. Only files inside the skill directories can be read."
            ),
            untrusted_output=True,
        )
        self._paths = SkillPaths(roots)

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="path", type="string", description="Absolute path of the file to read.")]

    async def acall(self, arguments: dict[str, object]) -> ToolOutcome:
        try:
            path = self._paths.resolve(str(arguments["path"]))
        except PathOutsideRootsError as error:
            return ToolOutcome.error(str(error))
        try:
            data = path.read_bytes()
        except OSError as error:
            return ToolOutcome.error(f"Failed to read {path}: {error}")
        if len(data) > MAX_READ_BYTES:
            return ToolOutcome.error(f"File is too large to read ({len(data)} bytes; limit {MAX_READ_BYTES}).")
        try:
            return ToolOutcome.ok(data.decode("utf-8"))
        except UnicodeDecodeError:
            return ToolOutcome.error(f"{path} is not a UTF-8 text file.")


class BashTool(Tool):
    """在技能目录里执行 shell 命令（跑技能自带脚本）。需要人工审批。"""

    def __init__(self, roots: Sequence[Path], *, timeout_seconds: float = DEFAULT_BASH_TIMEOUT_SECONDS) -> None:
        super().__init__(
            name="bash",
            description=(
                "Run a shell command and return its combined output. Use this to execute a skill's "
                "bundled scripts: the working directory must be (inside) a skill directory, and script "
                "paths are relative to it, as documented in the skill's SKILL.md."
            ),
            requires_approval=True,
            untrusted_output=True,
        )
        self._paths = SkillPaths(roots)
        self._timeout_seconds = timeout_seconds

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="command", type="string", description="Shell command to run."),
            ToolParameter(
                name="cwd",
                type="string",
                description=(
                    "Absolute working directory inside a skill directory. Defaults to the skill root."
                ),
                required=False,
            ),
        ]

    async def acall(self, arguments: dict[str, object]) -> ToolOutcome:
        raw_cwd = arguments.get("cwd")
        try:
            cwd = self._paths.resolve(str(raw_cwd)) if raw_cwd else self._paths.default_root
        except PathOutsideRootsError as error:
            return ToolOutcome.error(str(error))

        process = await asyncio.create_subprocess_shell(
            str(arguments["command"]),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self._timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()  # 回收进程，避免留下僵尸
            return ToolOutcome.ok("The command timed out before producing a result.")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            return ToolOutcome.ok(
                f"The command exited with code {process.returncode}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        return ToolOutcome.ok(stdout or "(no output)")
