import sqlite3
from pathlib import Path

import pytest

from db import ChatStore


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    return ChatStore(tmp_path / "chat.db")


def test_create_and_list_tasks(store: ChatStore) -> None:
    task = store.create_task("react")
    assert task["agent_type"] == "react"
    assert task["title"] == ""
    assert [t["id"] for t in store.list_tasks()] == [task["id"]]


def test_get_missing_task_returns_none(store: ChatStore) -> None:
    assert store.get_task("no-such-id") is None


def test_delete_task_cascades_messages(store: ChatStore) -> None:
    task = store.create_task("react")
    store.append_message(task["id"], "user", "hello")
    assert store.delete_task(task["id"]) is True
    assert store.get_task(task["id"]) is None
    assert store.list_messages(task["id"]) == []


def test_messages_round_trip_in_order(store: ChatStore) -> None:
    task = store.create_task("react")
    store.append_message(task["id"], "user", "你好")
    store.append_message(task["id"], "tool", '{"name":"read_skill","arguments":{"skill_name":"date"},"result":"r","ok":true}')
    store.append_message(task["id"], "assistant", "今天星期二")
    kinds = [m["kind"] for m in store.list_messages(task["id"])]
    assert kinds == ["user", "tool", "assistant"]


def test_title_set_only_once(store: ChatStore) -> None:
    task = store.create_task("react")
    store.set_title_if_empty(task["id"], "第一句话")
    store.set_title_if_empty(task["id"], "不应覆盖")
    assert store.get_task(task["id"])["title"] == "第一句话"


def test_update_task_renames_and_persists(store: ChatStore) -> None:
    task = store.create_task("react")
    updated = store.update_task(task["id"], title="新名字")
    assert updated is not None
    assert updated["title"] == "新名字"
    # 持久化：重新读取仍是新标题
    assert store.get_task(task["id"])["title"] == "新名字"


def test_update_task_missing_returns_none(store: ChatStore) -> None:
    assert store.update_task("no-such-id", title="x") is None


def test_update_task_ignores_non_whitelisted_columns(store: ChatStore) -> None:
    task = store.create_task("react")
    updated = store.update_task(task["id"], agent_type="toolcall", title="新标题")
    # 非白名单列被忽略，合法列 title 正常落地
    assert updated["agent_type"] == "react"
    assert updated["title"] == "新标题"


def test_append_unknown_kind_raises(store: ChatStore) -> None:
    task = store.create_task("react")
    with pytest.raises(ValueError):
        store.append_message(task["id"], "system", "x")


def test_list_tasks_orders_by_updated_at_desc(store: ChatStore) -> None:
    first = store.create_task("react")
    second = store.create_task("toolcall")
    store.append_message(first["id"], "user", "触碰旧任务")
    assert [t["id"] for t in store.list_tasks()] == [first["id"], second["id"]]


def test_task_defaults_to_unpinned(store: ChatStore) -> None:
    assert store.create_task("react")["pinned"] == 0


def test_pin_and_unpin_task_persists(store: ChatStore) -> None:
    task = store.create_task("react")
    pinned = store.update_task(task["id"], pinned=1)
    assert pinned is not None
    assert pinned["pinned"] == 1
    assert store.get_task(task["id"])["pinned"] == 1  # 持久化：重新读取仍已固定
    unpinned = store.update_task(task["id"], pinned=0)
    assert unpinned is not None
    assert unpinned["pinned"] == 0
    assert store.get_task(task["id"])["pinned"] == 0


def test_list_tasks_pinned_first_then_updated_at_desc(store: ChatStore) -> None:
    pinned = store.create_task("react")
    store.update_task(pinned["id"], pinned=1)
    plain_old = store.create_task("toolcall")
    plain_new = store.create_task("react")
    # 固定任务 updated_at 最旧仍排最前；普通组内按 updated_at 降序
    ids = [t["id"] for t in store.list_tasks()]
    assert ids == [pinned["id"], plain_new["id"], plain_old["id"]]


def test_legacy_db_without_pinned_column_migrates(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    # 构造旧 schema 库：tasks 表无 pinned 列且带一行旧数据
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " agent_type TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, agent_type, created_at, updated_at)"
        " VALUES ('t1', '旧任务', 'react', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    store = ChatStore(db_path)
    task = store.get_task("t1")
    assert task is not None
    assert task["pinned"] == 0  # 旧数据补默认值
    assert store.update_task("t1", pinned=1)["pinned"] == 1  # 迁移后可正常固定
