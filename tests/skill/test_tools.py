import sys
from pathlib import Path

import pytest

from skill.tools import BashTool, ReadTool
from tool.outcome import OutcomeStatus


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "skills" / "date"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# date\n\nusage...\n", encoding="utf-8")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "main.py").write_text("print('2026-09-22')\n", encoding="utf-8")
    return tmp_path / "skills"


async def test_read_returns_the_file_contents(skills_root: Path) -> None:
    tool = ReadTool([skills_root])

    outcome = await tool.acall({"path": str(skills_root / "date" / "SKILL.md")})

    assert outcome.status is OutcomeStatus.OK
    assert outcome.output == "# date\n\nusage...\n"


async def test_read_rejects_paths_outside_the_skill_roots(skills_root: Path) -> None:
    tool = ReadTool([skills_root])

    outcome = await tool.acall({"path": "/etc/hosts"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "outside" in outcome.output


async def test_read_rejects_relative_paths(skills_root: Path) -> None:
    tool = ReadTool([skills_root])

    outcome = await tool.acall({"path": "date/SKILL.md"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "absolute" in outcome.output


async def test_read_reports_non_utf8_files(skills_root: Path) -> None:
    binary = skills_root / "date" / "image.png"
    binary.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    tool = ReadTool([skills_root])

    outcome = await tool.acall({"path": str(binary)})

    assert outcome.status is OutcomeStatus.ERROR
    assert "UTF-8" in outcome.output


async def test_bash_runs_a_script_in_the_skill_directory(skills_root: Path) -> None:
    tool = BashTool([skills_root])

    outcome = await tool.acall(
        {"command": f'"{sys.executable}" scripts/main.py', "cwd": str(skills_root / "date")}
    )

    assert outcome.status is OutcomeStatus.OK
    assert "2026-09-22" in outcome.output


async def test_bash_requires_human_approval() -> None:
    tool = BashTool([Path("/tmp")])

    assert tool.requires_approval is True


async def test_bash_rejects_cwd_outside_the_skill_roots(skills_root: Path) -> None:
    tool = BashTool([skills_root])

    outcome = await tool.acall({"command": "echo hi", "cwd": "/etc"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "outside" in outcome.output


async def test_bash_reports_exit_code_and_stderr_on_failure(skills_root: Path) -> None:
    tool = BashTool([skills_root])

    outcome = await tool.acall(
        {"command": "echo boom >&2; exit 3", "cwd": str(skills_root / "date")}
    )

    assert outcome.status is OutcomeStatus.OK
    assert "code 3" in outcome.output
    assert "boom" in outcome.output
