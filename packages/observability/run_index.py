"""从磁盘上的运行轨迹（.data/traces/*.jsonl）扫描出列表摘要，供「运行记录」页面展示。

只读、不写文件；不改动 RunRecorder/html_report.py 的任何既有写入行为。
"""
import json
from pathlib import Path
from typing import Any

from .stats import summarize


def list_run_summaries(trace_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    """按 mtime 倒序扫描 trace_dir 下的 run-*.jsonl，取前 limit 份算出列表摘要。

    解析失败的残行（正在写入中的运行可能截断最后一行）直接跳过；完全解析不出
    session_start 事件的文件视为损坏，整份跳过。trace_dir 不存在时返回空列表。
    """
    if not trace_dir.is_dir():
        return []

    paths = sorted(trace_dir.glob("run-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    summaries: list[dict[str, Any]] = []
    for path in paths[:limit]:
        events = _read_events(path)
        session_start = next((e for e in events if e.get("event") == "session_start"), None)
        if session_start is None:
            continue
        session_end = next((e for e in reversed(events) if e.get("event") == "session_end"), None)
        meta = session_start.get("payload", {})
        stats = summarize(events)
        summaries.append({
            "session_id": path.stem,
            "agent_name": meta.get("agent_name"),
            "agent_type": meta.get("agent_type"),
            "task_id": meta.get("task_id"),
            "status": session_end["payload"].get("status") if session_end else "running",
            "started_at": session_start.get("ts"),
            "total_steps": stats["total_steps"],
            "total_tokens": stats["total_tokens"],
            "total_cost": stats["total_cost"],
            "duration_seconds": stats["duration_seconds"],
            "model_calls": stats["model_calls"],
        })
    return summaries


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
