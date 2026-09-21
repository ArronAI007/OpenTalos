import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import html_report
from .redaction import redact
from .stats import summarize


class RunRecorder:
    """记录一次 Agent 运行的轨迹：JSONL（流式追加，机器可读）+ HTML（增量渲染，人可读）。

    用法：
        recorder = RunRecorder(output_dir="traces")
        recorder.log_event("session_start", {"agent_name": "bot"})
        recorder.log_event("tool_call", {"tool_name": "echo"}, step=1)
        recorder.finalize()

    也可以当上下文管理器用，异常会自动记一条 error 事件（带完整 traceback）再 finalize。
    """

    def __init__(
        self,
        output_dir: str = "traces",
        redact_payloads: bool = True,
        include_raw_html: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.redact_payloads = redact_payloads
        self.include_raw_html = include_raw_html

        self.session_id = _new_session_id()
        self._events: list[dict[str, Any]] = []

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.output_dir / f"{self.session_id}.jsonl"
        self.html_path = self.output_dir / f"{self.session_id}.html"

        self._jsonl_file = self.jsonl_path.open("w", encoding="utf-8")
        self._html_file = self.html_path.open("w", encoding="utf-8")
        self._html_file.write(html_report.render_header(self.session_id))
        self._html_file.flush()

    def log_event(self, event: str, payload: dict[str, Any], step: int | None = None) -> None:
        record = {
            "ts": datetime.now().isoformat(),
            "session_id": self.session_id,
            "step": step,
            "event": event,
            "payload": redact(payload) if self.redact_payloads else payload,
        }
        self._events.append(record)

        self._jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._jsonl_file.flush()

        self._html_file.write(html_report.render_event(record, len(self._events)))
        self._html_file.flush()

    def finalize(self) -> dict[str, Any]:
        """写 HTML 尾部（统计面板）、关闭文件，返回本次运行的汇总统计。"""
        stats = summarize(self._events)
        self._html_file.write(html_report.render_footer(stats))
        self._jsonl_file.close()
        self._html_file.close()
        return stats

    def __enter__(self) -> "RunRecorder":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        if exc_type is not None:
            self.log_event(
                "error",
                {
                    "error_type": exc_type.__name__,
                    "message": str(exc_val),
                    "traceback": "".join(traceback.format_exception(exc_type, exc_val, exc_tb)),
                },
            )
        self.finalize()
        return False


def _new_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"run-{timestamp}-{uuid.uuid4().hex[:4]}"
