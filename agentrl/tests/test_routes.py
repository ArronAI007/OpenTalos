import asyncio
import threading

import httpx
import pytest

import main as main_module
from main import app


def _fake_run_training_job(config, *, on_metric, model_loader=None):
    on_metric("sft_loss", 1, 0.9)
    on_metric("grpo_reward", 1, 0.5)
    return {"comparisons": [{"question": "q", "before": "a", "after": "b", "expected": "c"}]}


@pytest.fixture(autouse=True)
def _isolated_store_and_fast_training(tmp_path, monkeypatch):
    # 默认全部用假训练函数——任何测试如果忘了桩住 run_training_job，就会意外跑真实的
    # Qwen3-0.6B（分钟级），这里用 autouse 杜绝这个坑；需要真跑的测试（如 409 用例）
    # 在自己的测试体里用更具体的 monkeypatch 覆盖这个默认值。
    from store import RunStore

    monkeypatch.setattr(main_module, "store", RunStore(tmp_path / "agentrl.db"))
    monkeypatch.setattr(main_module, "run_training_job", _fake_run_training_job)
    yield


async def test_create_run_starts_immediately_and_completes_in_background():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/runs", json={"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1}
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        assert created.json()["status"] == "running"

        for _ in range(50):
            fetched = await client.get(f"/runs/{run_id}")
            if fetched.json()["status"] != "running":
                break
            await asyncio.sleep(0.05)

        assert fetched.json()["status"] == "completed"
        assert fetched.json()["metrics"]["sft_loss"] == [0.9]
        assert fetched.json()["result"][0]["question"] == "q"


async def test_create_run_rejects_config_over_the_cap():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/runs", json={"sft_samples": 51, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1}
        )
    assert resp.status_code == 422


async def test_list_runs_orders_newest_first():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/runs", json={"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1})
        listed = await client.get("/runs")
    assert listed.status_code == 200
    assert len(listed.json()["runs"]) >= 1


async def test_delete_missing_run_returns_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/runs/no-such-id")
    assert resp.status_code == 404


async def test_delete_running_run_returns_409(monkeypatch):
    # run_training_job 卡在一个 Event 上不结束，确定性地模拟"仍在跑"的状态——
    # 用 Event 而不是 sleep()，断言完就立刻放行，不留悬挂的后台线程。
    block = threading.Event()

    def _blocking_fake(config, *, on_metric, model_loader=None):
        block.wait()
        return {"comparisons": []}

    monkeypatch.setattr(main_module, "run_training_job", _blocking_fake)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/runs", json={"sft_samples": 1, "sft_steps": 1, "grpo_samples": 1, "grpo_steps": 1}
        )
        run_id = created.json()["id"]
        resp = await client.delete(f"/runs/{run_id}")
    assert resp.status_code == 409
    block.set()  # 释放后台线程，避免遗留悬挂线程
