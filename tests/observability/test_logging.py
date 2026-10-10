import json
import logging

from observability.logging import JsonFormatter, configure_logging


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1, msg="hello %s", args=("world",), exc_info=None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_a_structured_line():
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "x"
    assert payload["message"] == "hello world"
    assert "ts" in payload


def test_json_formatter_passes_through_extra_fields():
    payload = json.loads(JsonFormatter().format(_record(task_id="t1", tool="echo")))
    assert payload["task_id"] == "t1"
    assert payload["tool"] == "echo"


def test_configure_logging_sets_the_root_level():
    try:
        configure_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG
    finally:
        configure_logging("INFO")
