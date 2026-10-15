"""DeepResearch 独立服务入口：FastAPI app + 5 个业务路由 + /health。镜像 agentrl/main.py
的组织方式——不依赖本仓库其他 apps/* 的代码，模型/搜索能力通过 research.py 的 sys.path 注入
复用 packages/ai、packages/websearch（见 research.md Decision 1）。"""
import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parent
_PACKAGES_DIR = _REPO_ROOT.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from ai.model import ModelClient  # noqa: E402
from websearch.client import TavilyClient  # noqa: E402

from research import run_research, start_live_run, stream_run_events  # noqa: E402
from store import DeepResearchStore  # noqa: E402

store = DeepResearchStore(_REPO_ROOT / ".data" / "deepresearch.db")

# 懒加载：不在服务启动时构造，避免 MODEL_PROVIDER/TAVILY_API_KEY 未配置时服务直接起不来
# （见 research.md Decision 3，和现状 apps/api ChatRuntime._client() 的取舍一致）。
_model_client: ModelClient | None = None
_search_client: TavilyClient | None = None


def _get_model_client() -> ModelClient:
    global _model_client
    if _model_client is None:
        _model_client = ModelClient()
    return _model_client


def _get_search_client() -> TavilyClient | None:
    global _search_client
    if _search_client is None and os.environ.get("TAVILY_API_KEY"):
        _search_client = TavilyClient(os.environ["TAVILY_API_KEY"])
    return _search_client


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


app = FastAPI(title="DeepResearch")
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


class CreateRunBody(BaseModel):
    topic: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/runs")
async def create_run_route(request: CreateRunBody) -> dict:
    search_client = _get_search_client()
    if search_client is None:
        raise HTTPException(503, "web search is not configured (TAVILY_API_KEY missing)")
    topic = request.topic.strip()
    if not topic:
        raise HTTPException(400, "topic must not be blank")
    run = store.create_run(topic)
    start_live_run(run["id"])
    asyncio.create_task(run_research(store, run["id"], _get_model_client(), search_client, topic))
    return run


@app.get("/runs")
async def list_runs_route() -> dict:
    return {"runs": store.list_runs()}


@app.get("/runs/{run_id}")
async def get_run_route(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/runs/{run_id}/stream")
async def stream_run_route(run_id: str) -> StreamingResponse:
    async def event_stream():
        async for event in stream_run_events(store, run_id):
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/runs/{run_id}", status_code=204)
async def delete_run_route(run_id: str) -> None:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run["status"] == "running":
        raise HTTPException(409, "run is still in progress")
    store.delete_run(run_id)
