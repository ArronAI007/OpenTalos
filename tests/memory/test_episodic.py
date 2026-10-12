from pathlib import Path

import pytest

from memory.episodic import EpisodicMemory


@pytest.fixture
def store(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "episodic.db")


def test_messages_round_trip_in_order(store: EpisodicMemory) -> None:
    store.append_message("t1", "user", "你好")
    store.append_message(
        "t1", "tool", '{"name":"read_skill","arguments":{"skill_name":"date"},"result":"r","ok":true}'
    )
    store.append_message("t1", "assistant", "今天星期二")

    kinds = [m["kind"] for m in store.list_messages("t1")]

    assert kinds == ["user", "tool", "assistant"]


def test_append_unknown_kind_raises(store: EpisodicMemory) -> None:
    with pytest.raises(ValueError):
        store.append_message("t1", "system", "x")


def _seed_two_turns(store: EpisodicMemory, task_id: str) -> list[dict]:
    return [
        store.append_message(task_id, "user", "一问"),
        store.append_message(task_id, "tool", '{"name":"echo","arguments":{},"result":"r","ok":true}'),
        store.append_message(task_id, "assistant", "一答"),
        store.append_message(task_id, "user", "二问"),
        store.append_message(task_id, "assistant", "二答"),
        store.append_message(task_id, "stopped", ""),
    ]


def test_delete_turn_removes_tail_turn(store: EpisodicMemory) -> None:
    rows = _seed_two_turns(store, "t1")

    assert store.delete_turn("t1", rows[3]["id"]) is True  # 「二问」起的轮次

    remaining = [(r["kind"], r["content"]) for r in store.list_messages("t1")]
    assert remaining == [("user", "一问"), ("tool", rows[1]["content"]), ("assistant", "一答")]


def test_delete_turn_removes_mid_turn_and_keeps_turn_boundary(store: EpisodicMemory) -> None:
    rows = _seed_two_turns(store, "t1")

    assert store.delete_turn("t1", rows[0]["id"]) is True  # 「一问」起的轮次

    remaining = [(r["kind"], r["content"]) for r in store.list_messages("t1")]
    assert remaining == [("user", "二问"), ("assistant", "二答"), ("stopped", "")]


def test_delete_turn_rejects_non_user_or_foreign_row(store: EpisodicMemory) -> None:
    rows = _seed_two_turns(store, "t1")
    _seed_two_turns(store, "t2")
    before = store.list_messages("t1")

    assert store.delete_turn("t1", rows[1]["id"]) is False  # tool 行不是轮次锚点
    assert store.delete_turn("t1", 999999) is False  # 不存在
    assert store.delete_turn("t2", rows[0]["id"]) is False  # 行不属于该任务

    assert store.list_messages("t1") == before  # 三次拒绝均一行未删
