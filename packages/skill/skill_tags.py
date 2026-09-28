import json
from pathlib import Path

_ENCODING = "utf-8"


def load_tags(store_path: Path) -> dict[str, list[str]]:
    if not store_path.is_file():
        return {}
    return json.loads(store_path.read_text(encoding=_ENCODING))


def get_tags(store_path: Path, name: str) -> list[str]:
    return load_tags(store_path).get(name, [])
