from pathlib import Path

from .json_store import load_json_store


def load_tags(store_path: Path) -> dict[str, list[str]]:
    return load_json_store(store_path)


def get_tags(store_path: Path, name: str) -> list[str]:
    return load_tags(store_path).get(name, [])
