from datetime import datetime
from typing import Any


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """从事件流水账里算出一次运行的汇总统计：步数、token/成本、按工具计数、错误列表、耗时。"""
    stats: dict[str, Any] = {
        "total_steps": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "tool_calls": {},
        "errors": [],
        "duration_seconds": 0.0,
        "model_calls": 0,
    }

    started_at: datetime | None = None
    finished_at: datetime | None = None

    for event in events:
        if event["event"] == "session_start":
            started_at = datetime.fromisoformat(event["ts"])
        if event["event"] == "session_end":
            finished_at = datetime.fromisoformat(event["ts"])

        step = event.get("step")
        if step:
            stats["total_steps"] = max(stats["total_steps"], step)

        if event["event"] == "model_output":
            usage = event.get("payload", {}).get("usage", {})
            stats["total_tokens"] += usage.get("total_tokens", 0)
            stats["total_cost"] += usage.get("cost", 0.0)
            stats["model_calls"] += 1

        if event["event"] == "tool_call":
            tool_name = event["payload"].get("tool_name", "unknown")
            stats["tool_calls"][tool_name] = stats["tool_calls"].get(tool_name, 0) + 1

        if event["event"] == "error":
            stats["errors"].append(
                {
                    "step": event.get("step"),
                    "type": event["payload"].get("error_type"),
                    "message": event["payload"].get("message"),
                }
            )

    if started_at and finished_at:
        stats["duration_seconds"] = (finished_at - started_at).total_seconds()

    return stats
