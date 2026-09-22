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


def test_append_unknown_kind_raises(store: ChatStore) -> None:
    task = store.create_task("react")
    with pytest.raises(ValueError):
        store.append_message(task["id"], "system", "x")


def test_list_tasks_orders_by_updated_at_desc(store: ChatStore) -> None:
    first = store.create_task("react")
    second = store.create_task("toolcall")
    store.append_message(first["id"], "user", "触碰旧任务")
    assert [t["id"] for t in store.list_tasks()] == [first["id"], second["id"]]
