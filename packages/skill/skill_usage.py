import json
from pathlib import Path

_ENCODING = "utf-8"


def load_usage(store_path: Path) -> dict[str, int]:
    if not store_path.is_file():
        return {}
    return json.loads(store_path.read_text(encoding=_ENCODING))


def get_usage_count(store_path: Path, name: str) -> int:
    return load_usage(store_path).get(name, 0)


def increment_usage(store_path: Path, name: str) -> int:
    usage = load_usage(store_path)
    usage[name] = usage.get(name, 0) + 1
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(usage), encoding=_ENCODING)
    return usage[name]
