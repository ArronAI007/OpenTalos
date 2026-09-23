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


def test_task_defaults_to_unpinned_and_unstarred(store: ChatStore) -> None:
    task = store.create_task("react")
    assert task["pinned"] == 0
    assert task["starred"] == 0


def test_task_defaults_to_unarchived(store: ChatStore) -> None:
    task = store.create_task("react")
    assert task["archived"] == 0


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


def test_star_and_unstar_task_persists(store: ChatStore) -> None:
    task = store.create_task("react")
    starred = store.update_task(task["id"], starred=1)
    assert starred is not None
    assert starred["starred"] == 1
    assert store.get_task(task["id"])["starred"] == 1  # 持久化：重新读取仍已收藏
    unstarred = store.update_task(task["id"], starred=0)
    assert unstarred is not None
    assert unstarred["starred"] == 0
    assert store.get_task(task["id"])["starred"] == 0


def test_list_tasks_pinned_then_starred_then_plain(store: ChatStore) -> None:
    pinned = store.create_task("react")
    store.update_task(pinned["id"], pinned=1)
    starred_old = store.create_task("react")
    store.update_task(starred_old["id"], starred=1)
    starred_new = store.create_task("react")
    store.update_task(starred_new["id"], starred=1)
    plain_old = store.create_task("toolcall")
    plain_new = store.create_task("react")
    # 次序：固定 > 收藏 > 普通，各组内 updated_at 降序；注意收藏/固定操作会刷新
    # updated_at，故 starred_old 比两个普通任务更旧，仍须排在普通组之前。
    ids = [t["id"] for t in store.list_tasks()]
    assert ids == [pinned["id"], starred_new["id"], starred_old["id"], plain_new["id"], plain_old["id"]]


def test_archive_and_unarchive_task_persists(store: ChatStore) -> None:
    task = store.create_task("react")
    archived = store.update_task(task["id"], archived=1)
    assert archived is not None
    assert archived["archived"] == 1
    assert store.get_task(task["id"])["archived"] == 1  # 持久化：重新读取仍已归档
    restored = store.update_task(task["id"], archived=0)
    assert restored is not None
    assert restored["archived"] == 0
    assert store.get_task(task["id"])["archived"] == 0


def test_list_tasks_excludes_archived(store: ChatStore) -> None:
    alive = store.create_task("react")
    gone = store.create_task("toolcall")
    store.update_task(gone["id"], archived=1)
    assert [t["id"] for t in store.list_tasks()] == [alive["id"]]
    assert [t["id"] for t in store.list_archived_tasks()] == [gone["id"]]


def test_list_archived_tasks_orders_by_updated_at_desc(store: ChatStore) -> None:
    old = store.create_task("react")
    store.update_task(old["id"], archived=1)
    new = store.create_task("toolcall")
    store.update_task(new["id"], archived=1)
    store.create_task("react")  # 未归档任务不进归档列表
    # 后归档的 new updated_at 更新，排在最前
    assert [t["id"] for t in store.list_archived_tasks()] == [new["id"], old["id"]]


def test_task_defaults_to_no_project(store: ChatStore) -> None:
    task = store.create_task("react")
    assert task["project_id"] is None


def test_create_and_list_projects(store: ChatStore) -> None:
    project = store.create_project("调研")
    assert project["name"] == "调研"
    assert project["id"]
    assert project["created_at"]
    assert [p["id"] for p in store.list_projects()] == [project["id"]]


def test_list_projects_orders_by_created_at_desc(store: ChatStore) -> None:
    first = store.create_project("最早")
    second = store.create_project("最新")
    # 最新创建的项目排最前
    assert [p["id"] for p in store.list_projects()] == [second["id"], first["id"]]


def test_get_missing_project_returns_none(store: ChatStore) -> None:
    assert store.get_project("no-such-id") is None


def test_update_task_sets_and_clears_project(store: ChatStore) -> None:
    task = store.create_task("react")
    project = store.create_project("调研")
    moved = store.update_task(task["id"], project_id=project["id"])
    assert moved is not None
    assert moved["project_id"] == project["id"]
    assert store.get_task(task["id"])["project_id"] == project["id"]  # 持久化：重新读取仍已归组
    cleared = store.update_task(task["id"], project_id=None)  # 显式 None = 移出项目
    assert cleared is not None
    assert cleared["project_id"] is None
    assert store.get_task(task["id"])["project_id"] is None


def test_legacy_db_without_projects_table_creates_it(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    # 构造旧库：仅 tasks 表，无 projects 表。_SCHEMA 在每次构造时整段执行，
    # CREATE TABLE IF NOT EXISTS 对既有库直接补建新表（与列级 _MIGRATIONS 不同）。
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " agent_type TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    store = ChatStore(db_path)
    assert store.list_projects() == []
    project = store.create_project("新项目")
    assert store.get_project(project["id"]) is not None


def test_legacy_db_without_project_id_column_migrates(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    # 构造 T5 时点 schema：有 pinned/starred/archived，无 project_id 列且带一行旧数据
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " agent_type TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
        " pinned INTEGER NOT NULL DEFAULT 0, starred INTEGER NOT NULL DEFAULT 0,"
        " archived INTEGER NOT NULL DEFAULT 0)"
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
    assert task["project_id"] is None  # 旧数据补空（可空列）
    assert store.update_task("t1", project_id="p1")["project_id"] == "p1"  # 迁移后可正常归组


def test_legacy_db_without_flag_columns_migrates(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    # 构造旧 schema 库：tasks 表无 pinned/starred/archived 列且带一行旧数据
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
    assert task["starred"] == 0
    assert task["archived"] == 0
    assert store.update_task("t1", pinned=1)["pinned"] == 1  # 迁移后可正常固定
    assert store.update_task("t1", starred=1)["starred"] == 1  # 迁移后可正常收藏
    assert store.update_task("t1", archived=1)["archived"] == 1  # 迁移后可正常归档
