"""小型 JSON 键值存储的通用读写：skill_tags.py/skill_usage.py 共用同一套样板。"""
import json
from pathlib import Path

_ENCODING = "utf-8"


def load_json_store(store_path: Path) -> dict:
    if not store_path.is_file():
        return {}
    return json.loads(store_path.read_text(encoding=_ENCODING))


def write_json_store(store_path: Path, data: dict) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(data), encoding=_ENCODING)
