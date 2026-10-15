from pathlib import Path

import pytest

from store import DeepResearchStore


@pytest.fixture
def store(tmp_path: Path) -> DeepResearchStore:
    return DeepResearchStore(tmp_path / "deepresearch.db")


def test_create_and_get_run(store: DeepResearchStore) -> None:
    run = store.create_run("quantum computing basics")
    assert run["id"]
    assert run["status"] == "running"
    assert run["topic"] == "quantum computing basics"
    assert run["todos"] == []
    assert run["report"] is None
    assert run["error"] is None
    assert store.get_run(run["id"]) == run


def test_get_missing_run_returns_none(store: DeepResearchStore) -> None:
    assert store.get_run("no-such-id") is None


def test_list_runs_orders_newest_first(store: DeepResearchStore) -> None:
    first = store.create_run("topic a")
    second = store.create_run("topic b")
    assert [r["id"] for r in store.list_runs()] == [second["id"], first["id"]]


def test_update_run_todos_replaces_the_list(store: DeepResearchStore) -> None:
    run = store.create_run("topic")
    todos = [{"id": 0, "query": "q1", "status": "pending", "summary": None, "sources": []}]
    store.update_run_todos(run["id"], todos)
    assert store.get_run(run["id"])["todos"] == todos


def test_update_todo_patches_one_entry_by_id(store: DeepResearchStore) -> None:
    run = store.create_run("topic")
    todos = [
        {"id": 0, "query": "q1", "status": "pending", "summary": None, "sources": []},
        {"id": 1, "query": "q2", "status": "pending", "summary": None, "sources": []},
    ]
    store.update_run_todos(run["id"], todos)
    store.update_todo(run["id"], 1, status="completed", summary="done", sources=[{"title": "t", "url": "u"}])
    updated = store.get_run(run["id"])["todos"]
    assert updated[0]["status"] == "pending"
    assert updated[1] == {"id": 1, "query": "q2", "status": "completed", "summary": "done", "sources": [{"title": "t", "url": "u"}]}


def test_update_todo_missing_run_is_a_noop(store: DeepResearchStore) -> None:
    store.update_todo("no-such-id", 0, status="completed")  # 不应抛异常


def test_update_run_sets_only_passed_fields(store: DeepResearchStore) -> None:
    run = store.create_run("topic")
    updated = store.update_run(run["id"], status="completed", report="# Report")
    assert updated["status"] == "completed"
    assert updated["report"] == "# Report"
    assert updated["error"] is None

    failed = store.create_run("topic")
    updated_failed = store.update_run(failed["id"], status="failed", error="boom")
    assert updated_failed["status"] == "failed"
    assert updated_failed["error"] == "boom"


def test_update_run_missing_id_returns_none(store: DeepResearchStore) -> None:
    assert store.update_run("no-such-id", status="completed") is None


def test_delete_run_removes_it(store: DeepResearchStore) -> None:
    run = store.create_run("topic")
    assert store.delete_run(run["id"]) is True
    assert store.get_run(run["id"]) is None


def test_delete_missing_run_returns_false(store: DeepResearchStore) -> None:
    assert store.delete_run("no-such-id") is False
