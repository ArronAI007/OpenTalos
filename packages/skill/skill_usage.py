from pathlib import Path

from .json_store import load_json_store, write_json_store


def load_usage(store_path: Path) -> dict[str, int]:
    return load_json_store(store_path)


def get_usage_count(store_path: Path, name: str) -> int:
    return load_usage(store_path).get(name, 0)


def increment_usage(store_path: Path, name: str) -> int:
    usage = load_usage(store_path)
    usage[name] = usage.get(name, 0) + 1
    write_json_store(store_path, usage)
    return usage[name]
