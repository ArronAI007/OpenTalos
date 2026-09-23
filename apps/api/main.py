"""聊天会话 API：浏览器前端（apps/web）的唯一后端。启动方式见 scripts/start.sh。"""
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGES_DIR = _REPO_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from agents.builder import AGENT_TYPES  # noqa: E402
from db import ChatStore  # noqa: E402
from runtime import ChatRuntime  # noqa: E402


class CreateTaskRequest(BaseModel):
    agent_type: str


class PostMessageRequest(BaseModel):
    content: str


class UpdateTaskRequest(BaseModel):
    # 字段均可选但至少要有一个；布尔 flag 与 _FLAG_FIELDS 一一对应，PATCH 端点统一循环装配。
    title: str | None = None
    pinned: bool | None = None
    starred: bool | None = None
    archived: bool | None = None


# 任务的布尔 flag 字段：PATCH 端点按下表统一装配，新增 flag 只需在此处与模型各加一行。
_FLAG_FIELDS = ("pinned", "starred", "archived")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(runtime: ChatRuntime | None = None) -> FastAPI:
    if runtime is None:
        runtime = ChatRuntime(
            ChatStore(_REPO_ROOT / ".data" / "chat.db"),
            skill_service_url=os.environ.get("SKILL_SERVICE_URL", "http://localhost:8321"),
            trace_dir=_REPO_ROOT / ".data" / "traces",
        )
    app = FastAPI(title="OpenTalos Chat API")
    app.state.runtime = runtime
    cors_origins = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins,
        allow_methods=["*"], allow_headers=["*"],
    )
    store = runtime.store

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    async def config() -> dict:
        model_name = None
        try:
            model_name = runtime.model_name
        except Exception:  # noqa: BLE001 - 配置未就绪时如实返回 null
            pass
        return {
            "model_name": model_name,
            "agent_types": sorted(AGENT_TYPES.keys()),
            "skills_reachable": runtime.skills_reachable,
        }

    @app.get("/api/tasks")
    async def list_tasks(archived: int = Query(0, ge=0, le=1)) -> dict:
        # archived 用 query 而非子路径：避开与 /api/tasks/{task_id} 的路径歧义。
        # int + 范围约束 0..1：query 字符串能正常强转，非 0/1 一律 422。
        # （不用 Literal[0, 1]——pydantic v2 的字面量校验不做字符串强转，"1" 会被误判 422。）
        tasks = store.list_archived_tasks() if archived else store.list_tasks()
        return {"tasks": tasks}

    @app.post("/api/tasks", status_code=201)
    async def create_task(request: CreateTaskRequest) -> dict:
        if request.agent_type not in AGENT_TYPES:
            raise HTTPException(422, f"unknown agent_type: {request.agent_type}")
        return store.create_task(request.agent_type)

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: UpdateTaskRequest) -> dict:
        # 校验顺序保持 422（全 None）→ 400（title 空白）→ 404（任务不存在）。
        if request.title is None and all(
            getattr(request, field) is None for field in _FLAG_FIELDS
        ):
            raise HTTPException(422, "no updatable field provided")
        # 收集式装配待更新字段：title 去首尾空白，flag 布尔统一转 SQLite 0/1。
        fields: dict[str, str | int] = {}
        if request.title is not None:
            title = request.title.strip()
            if not title:
                raise HTTPException(400, "title must not be blank")
            fields["title"] = title
        for field in _FLAG_FIELDS:
            value = getattr(request, field)
            if value is not None:
                fields[field] = 1 if value else 0
        updated = store.update_task(task_id, **fields)
        if updated is None:
            raise HTTPException(404, "task not found")
        return updated

    @app.delete("/api/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str) -> None:
        if not store.delete_task(task_id):
            raise HTTPException(404, "task not found")
        runtime.evict(task_id)

    @app.get("/api/tasks/{task_id}/messages")
    async def list_messages(task_id: str) -> dict:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        return {"messages": store.list_messages(task_id)}

    @app.post("/api/tasks/{task_id}/messages")
    async def post_message(task_id: str, request: PostMessageRequest) -> StreamingResponse:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")

        async def event_stream():
            async for event in runtime.stream_reply(task_id, request.content):
                yield _sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/skills")
    async def list_skills() -> dict:
        from skill.client import SkillClient, SkillServiceError
        try:
            skills = await SkillClient(runtime.skill_service_url).list_skills()
            return {"reachable": True, "skills": [s.model_dump() for s in skills]}
        except SkillServiceError as error:
            return {"reachable": False, "skills": [], "error": str(error)}

    return app


app = create_app()
