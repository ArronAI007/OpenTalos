from pathlib import Path

from skill.json_store import load_json_store, write_json_store


def test_load_json_store_returns_empty_dict_when_file_is_missing(tmp_path: Path):
    store_path = tmp_path / "store.json"

    assert load_json_store(store_path) == {}


def test_load_json_store_reads_an_existing_file(tmp_path: Path):
    store_path = tmp_path / "store.json"
    store_path.write_text('{"date": 3}', encoding="utf-8")

    assert load_json_store(store_path) == {"date": 3}


def test_write_json_store_creates_parent_dirs_and_persists(tmp_path: Path):
    store_path = tmp_path / "nested" / "store.json"

    write_json_store(store_path, {"date": 1})

    assert load_json_store(store_path) == {"date": 1}


def test_write_json_store_overwrites_existing_content(tmp_path: Path):
    store_path = tmp_path / "store.json"
    write_json_store(store_path, {"date": 1})

    write_json_store(store_path, {"date": 2})

    assert load_json_store(store_path) == {"date": 2}
