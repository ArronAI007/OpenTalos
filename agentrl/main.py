"""AgentRL：独立的 SFT→GRPO 训练演示服务，不依赖本仓库其他任何包。"""
import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from store import RunStore
from training import run_training_job

_REPO_ROOT = Path(__file__).resolve().parent
_MAX_SAMPLES = 50
_MAX_STEPS = 50

store = RunStore(_REPO_ROOT / ".data" / "agentrl.db")

app = FastAPI()
# 与 apps/api/main.py 同款约定：CORS_ORIGINS 由 scripts/start.sh 按 web 端口导出，
# 独立跑（不经 start.sh）时默认放行 :3000。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateRunRequest(BaseModel):
    sft_samples: int = Field(ge=1, le=_MAX_SAMPLES)
    sft_steps: int = Field(ge=1, le=_MAX_STEPS)
    grpo_samples: int = Field(ge=1, le=_MAX_SAMPLES)
    grpo_steps: int = Field(ge=1, le=_MAX_STEPS)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _execute_in_background(run_id: str, config: dict) -> None:
    try:
        result = run_training_job(
            config,
            on_metric=lambda phase, _step, value: store.append_metric(run_id, phase, value),
        )
        store.update_run(run_id, status="completed", result=result["comparisons"])
    except Exception as exc:  # noqa: BLE001 - 失败要落库给前端看，不能让后台线程静默吞掉
        store.update_run(run_id, status="failed", error=str(exc))


@app.post("/runs")
async def create_run(request: CreateRunRequest) -> dict:
    config = request.model_dump()
    run = store.create_run(config)
    asyncio.create_task(asyncio.to_thread(_execute_in_background, run["id"], config))
    return run


@app.get("/runs")
async def list_runs() -> dict:
    return {"runs": store.list_runs()}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str) -> None:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run["status"] == "running":
        raise HTTPException(409, "run is still in progress")
    store.delete_run(run_id)
