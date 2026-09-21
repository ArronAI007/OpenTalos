import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

TrimMode = Literal["head", "tail", "head_tail"]


@dataclass
class TrimResult:
    trimmed: bool
    preview: str
    full_output_path: str | None
    stats: dict[str, Any] = field(default_factory=dict)


class OutputTrimmer:
    """统一裁剪工具输出，超限时把完整输出落盘，返回摘要预览。"""

    def __init__(
        self,
        max_lines: int = 2000,
        max_bytes: int = 51_200,
        mode: TrimMode = "head",
        output_dir: str = "tool-output",
    ) -> None:
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.mode = mode
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def trim(self, tool_name: str, output: str, metadata: dict[str, Any] | None = None) -> TrimResult:
        start = time.monotonic()
        lines = output.splitlines()
        byte_size = len(output.encode("utf-8"))

        if len(lines) <= self.max_lines and byte_size <= self.max_bytes:
            return TrimResult(
                trimmed=False,
                preview=output,
                full_output_path=None,
                stats={
                    "original_lines": len(lines),
                    "original_bytes": byte_size,
                    "time_ms": int((time.monotonic() - start) * 1000),
                },
            )

        kept_lines = self._select_lines(lines)
        preview = "\n".join(kept_lines)
        saved_path = self._persist(tool_name, output, metadata)

        return TrimResult(
            trimmed=True,
            preview=preview,
            full_output_path=str(saved_path),
            stats={
                "mode": self.mode,
                "original_lines": len(lines),
                "original_bytes": byte_size,
                "kept_lines": len(kept_lines),
                "kept_bytes": len(preview.encode("utf-8")),
                "time_ms": int((time.monotonic() - start) * 1000),
            },
        )

    def _select_lines(self, lines: list[str]) -> list[str]:
        if self.mode == "tail":
            return lines[-self.max_lines :]
        if self.mode == "head_tail":
            half = self.max_lines // 2
            return lines[:half] + ["...(truncated)..."] + lines[-half:]
        return lines[: self.max_lines]

    def _persist(self, tool_name: str, output: str, metadata: dict[str, Any] | None) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.output_dir / f"{tool_name}_{timestamp}.json"
        payload = {
            "tool": tool_name,
            "output": output,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
