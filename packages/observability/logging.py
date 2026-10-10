"""结构化日志：JSON 行输出到 stderr，固定字段 ts/level/logger/message，附加字段直通。

进程启动时用 configure_logging() 配置一次（级别取参数或 LOG_LEVEL，默认 INFO）；库模块只用
标准 logging.getLogger(__name__)，不自行配置 handler。这样进程日志（uvicorn/应用）都是可机
读的一行一个 JSON，便于采集与检索。
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

# 标准 LogRecord 自带的属性（以及 Formatter 注入的 message/asctime），其余视为结构化附加字段。
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None) -> None:
    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(resolved)
