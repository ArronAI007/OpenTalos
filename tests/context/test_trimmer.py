import json

from context.trimmer import OutputTrimmer


def test_trim_returns_untouched_output_when_within_limits(tmp_path):
    trimmer = OutputTrimmer(max_lines=10, max_bytes=1000, output_dir=str(tmp_path))
    result = trimmer.trim("echo", "line1\nline2")

    assert result.trimmed is False
    assert result.preview == "line1\nline2"
    assert result.full_output_path is None


def test_trim_by_line_count_keeps_the_head_by_default(tmp_path):
    trimmer = OutputTrimmer(max_lines=3, max_bytes=1_000_000, output_dir=str(tmp_path))
    output = "\n".join(f"line{i}" for i in range(10))

    result = trimmer.trim("echo", output)

    assert result.trimmed is True
    assert result.preview == "line0\nline1\nline2"
    assert result.stats["kept_lines"] == 3


def test_trim_tail_mode_keeps_the_last_lines(tmp_path):
    trimmer = OutputTrimmer(max_lines=3, max_bytes=1_000_000, mode="tail", output_dir=str(tmp_path))
    output = "\n".join(f"line{i}" for i in range(10))

    result = trimmer.trim("echo", output)

    assert result.preview == "line7\nline8\nline9"


def test_trim_head_tail_mode_keeps_both_ends(tmp_path):
    output = "\n".join(f"line{i}" for i in range(10))
    trimmer = OutputTrimmer(max_lines=4, max_bytes=1_000_000, mode="head_tail", output_dir=str(tmp_path))

    result = trimmer.trim("echo", output)

    assert result.preview.startswith("line0\nline1")
    assert result.preview.endswith("line8\nline9")
    assert "...(truncated)..." in result.preview


def test_trim_persists_the_full_output_to_disk_when_trimmed(tmp_path):
    trimmer = OutputTrimmer(max_lines=2, max_bytes=1_000_000, output_dir=str(tmp_path))
    output = "\n".join(f"line{i}" for i in range(10))

    result = trimmer.trim("my-tool", output, metadata={"query": "test"})

    assert result.full_output_path is not None
    saved = json.loads((tmp_path / result.full_output_path.split("/")[-1]).read_text(encoding="utf-8"))
    assert saved["tool"] == "my-tool"
    assert saved["output"] == output
    assert saved["metadata"] == {"query": "test"}


def test_trim_by_byte_size_triggers_even_with_few_lines(tmp_path):
    trimmer = OutputTrimmer(max_lines=1000, max_bytes=10, output_dir=str(tmp_path))
    result = trimmer.trim("echo", "a" * 100)
    assert result.trimmed is True
