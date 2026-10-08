import json
from pathlib import Path

import pytest

from store import RunStore


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agentrl.db")


def test_create_and_get_run(store: RunStore) -> None:
    config = {"sft_samples": 2, "sft_steps": 2, "grpo_samples": 2, "grpo_steps": 2}
    run = store.create_run(config)
    assert run["id"]
    assert run["status"] == "running"
    assert run["config"] == config
    assert run["metrics"] == {"sft_loss": [], "grpo_reward": []}
    assert run["result"] is None
    assert run["error"] is None
    assert store.get_run(run["id"]) == run


def test_get_missing_run_returns_none(store: RunStore) -> None:
    assert store.get_run("no-such-id") is None


def test_list_runs_orders_newest_first(store: RunStore) -> None:
    first = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    second = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    assert [r["id"] for r in store.list_runs()] == [second["id"], first["id"]]


def test_append_metric_accumulates(store: RunStore) -> None:
    run = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    store.append_metric(run["id"], "sft_loss", 1.2)
    store.append_metric(run["id"], "sft_loss", 0.9)
    store.append_metric(run["id"], "grpo_reward", 0.5)
    updated = store.get_run(run["id"])
    assert updated["metrics"] == {"sft_loss": [1.2, 0.9], "grpo_reward": [0.5]}


def test_update_run_sets_status_result_and_error(store: RunStore) -> None:
    run = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    result = [{"question": "q", "before": "a", "after": "b", "expected": "c"}]
    updated = store.update_run(run["id"], status="completed", result=result)
    assert updated["status"] == "completed"
    assert updated["result"] == result
    assert updated["error"] is None

    failed = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    updated_failed = store.update_run(failed["id"], status="failed", error="boom")
    assert updated_failed["status"] == "failed"
    assert updated_failed["error"] == "boom"


def test_delete_run_removes_it(store: RunStore) -> None:
    run = store.create_run({"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
    assert store.delete_run(run["id"]) is True
    assert store.get_run(run["id"]) is None


def test_delete_missing_run_returns_false(store: RunStore) -> None:
    assert store.delete_run("no-such-id") is False
