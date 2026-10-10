"""聊天会话 API：浏览器前端（apps/web）的唯一后端。启动方式见 scripts/start.sh。"""
import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGES_DIR = _REPO_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from db import ChatStore  # noqa: E402
from deepresearch import run_research, start_live_run, stream_run_events  # noqa: E402
from mcpclient.client import MCPConnectionError, MCPServerConfig, connect_and_list_tools  # noqa: E402
from evaluation import (  # noqa: E402
    EVAL_AGENT_TYPES,
    add_eval_case,
    load_eval_cases,
    remove_eval_case,
    run_case,
)
from runtime import ChatRuntime  # noqa: E402
from observability import configure_logging, metrics  # noqa: E402
from skill.discovery import discover_skills, list_skill_files  # noqa: E402
from skill.frontmatter import extract_frontmatter_text, parse_frontmatter  # noqa: E402
from skill.github_import import (  # noqa: E402
    GithubImportError,
    import_github_skills,
    scan_github_repo,
    validate_repo_url,
)
from skill.my_skills import add_my_skill, load_my_skills, remove_my_skill  # noqa: E402
from skill.skill_tags import load_tags  # noqa: E402
from skill.skill_upload import SkillUploadError, extract_uploaded_skill  # noqa: E402
from skill.skill_usage import load_usage  # noqa: E402

# 技能是仓库 skills/ 下的文件系统目录（pi 式方案，无独立服务）；
# my_skills/tags/usage 这些可变状态落在 .data/ 下。测试按需 monkeypatch 这几个模块级常量。
_SKILLS_ROOT = _REPO_ROOT / "skills"
_MY_SKILLS_PATH = _REPO_ROOT / ".data" / "my_skills.json"
_SKILL_TAGS_PATH = _REPO_ROOT / ".data" / "skill_tags.json"
_SKILL_USAGE_PATH = _REPO_ROOT / ".data" / "skill_usage.json"

# 进程启动即装好结构化日志（JSON 行到 stderr）；级别取 LOG_LEVEL（默认 INFO）。
configure_logging()


class CreateTaskRequest(BaseModel):
    pass


class PostMessageRequest(BaseModel):
    content: str


class UpdateTaskRequest(BaseModel):
    # 字段均可选但至少要有一个；布尔 flag 与 _FLAG_FIELDS 一一对应，PATCH 端点统一循环装配。
    # project_id 不走 flag 通道：None 既是"未提供"又是"移出项目"的合法值，端点用
    # model_fields_set 区分（显式 null → SET NULL）。
    title: str | None = None
    pinned: bool | None = None
    starred: bool | None = None
    archived: bool | None = None
    project_id: str | None = None


class CreateProjectRequest(BaseModel):
    name: str


class GithubScanBody(BaseModel):
    repo_url: str


class GithubImportBody(BaseModel):
    repo_url: str
    relative_paths: list[str]


class SkillUsageExamplesBody(BaseModel):
    description: str


class EvalCaseBody(BaseModel):
    name: str
    instruction: str
    expected_answer: str | None = None


class EvalRunBody(BaseModel):
    case_ids: list[str]
    agent_types: list[str]


class CreateDeepResearchRunBody(BaseModel):
    topic: str


class CreateMCPServerBody(BaseModel):
    name: str
    transport: str  # 'stdio' | 'http'
    command: str | None = None
    args: list[str] = []
    url: str | None = None


class ApprovalDecisionBody(BaseModel):
    approved: bool


class UpdateMCPServerBody(BaseModel):
    enabled: bool


# 任务的布尔 flag 字段：PATCH 端点按下表统一装配，新增 flag 只需在此处与模型各加一行。
_FLAG_FIELDS = ("pinned", "starred", "archived")


def _sse(event: dict) -> str:
    # ping 只是探活不是聊天事件：编成 SSE comment 帧，前端 parseSseBlock 天然忽略。
    # 唯二作用：保持连接、让客户端断开在下次写时暴露（uvicorn 只在写响应时发现断开）。
    if event["type"] == "ping":
        return ": keep-alive\n\n"
    # 事件下标编成 SSE id（重连据此续传）；`_id` 是内部字段，不进 data。
    event_id = event.get("_id")
    payload = {key: value for key, value in event.items() if key != "_id"}
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app(runtime: ChatRuntime | None = None, eval_cases_path: Path | None = None) -> FastAPI:
    if runtime is None:
        runtime = ChatRuntime(
            ChatStore(_REPO_ROOT / ".data" / "chat.db"),
            tavily_api_key=os.environ.get("TAVILY_API_KEY"),
            a2a_peer_url=os.environ.get("A2A_PEER_URL"),
            trace_dir=_REPO_ROOT / ".data" / "traces",
            compaction_token_limit=int(os.environ.get("COMPACTION_TOKEN_LIMIT", "16000")),
            # 工具可靠性安全网（各工具自身超时更短，这里只是兵底）：空值回退到默认。
            tool_timeout_seconds=float(os.environ.get("TOOL_TIMEOUT_SECONDS") or 120),
            circuit_failure_threshold=int(os.environ.get("TOOL_CIRCUIT_FAILURE_THRESHOLD") or 3),
            circuit_recovery_seconds=float(os.environ.get("TOOL_CIRCUIT_RECOVERY_SECONDS") or 300),
            approval_timeout_seconds=float(os.environ.get("APPROVAL_TIMEOUT_SECONDS") or 300),
            memory_enabled=os.environ.get("MEMORY_ENABLED", "0") == "1",
            budget_tokens=int(os.environ["TASK_TOKEN_BUDGET"]) if os.environ.get("TASK_TOKEN_BUDGET") else None,
        )
    if eval_cases_path is None:
        eval_cases_path = _REPO_ROOT / ".data" / "eval_cases.json"

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        try:
            yield
        finally:
            # 进程关闭时释放 runtime 懒构造的模型客户端（httpx 连接池）。
            await app.state.runtime.aclose()

    app = FastAPI(title="OpenTalos Chat API", lifespan=_lifespan)
    app.state.runtime = runtime

    @app.middleware("http")
    async def _record_http_metrics(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        metrics.inc(
            "opentalos_http_requests_total",
            labels={"method": request.method, "path": path, "status": str(response.status_code)},
        )
        metrics.observe(
            "opentalos_http_request_duration_seconds",
            time.perf_counter() - started,
            labels={"method": request.method, "path": path},
        )
        return response
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

    @app.get("/metrics")
    async def metrics_route() -> PlainTextResponse:
        # Prometheus 文本导出（无第三方依赖）。
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/api/config")
    async def config() -> dict:
        model_name = None
        try:
            model_name = runtime.model_name
        except Exception:  # noqa: BLE001 - 配置未就绪时如实返回 null
            pass
        return {
            "model_name": model_name,
            "agent_types": EVAL_AGENT_TYPES,
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
        return store.create_task("react")

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: UpdateTaskRequest) -> dict:
        # 校验顺序保持 422（无有效字段）→ 400（title 空白 / 项目不存在）→ 404（任务不存在）。
        # project_id 例外：显式 null 是合法的"移出项目"操作，不算"未提供"——以 model_fields_set 为准。
        if (
            request.title is None
            and all(getattr(request, field) is None for field in _FLAG_FIELDS)
            and "project_id" not in request.model_fields_set
        ):
            raise HTTPException(422, "no updatable field provided")
        # 收集式装配待更新字段：title 去首尾空白，flag 布尔统一转 SQLite 0/1。
        fields: dict[str, str | int | None] = {}
        if request.title is not None:
            title = request.title.strip()
            if not title:
                raise HTTPException(400, "title must not be blank")
            fields["title"] = title
        for field in _FLAG_FIELDS:
            value = getattr(request, field)
            if value is not None:
                fields[field] = 1 if value else 0
        if "project_id" in request.model_fields_set:
            # 项目不存在返回 400 而非 404：避免与"任务不存在"的 404 歧义
            if request.project_id is not None and store.get_project(request.project_id) is None:
                raise HTTPException(400, "project not found")
            fields["project_id"] = request.project_id  # 显式 null → 置 NULL 移出项目
        updated = store.update_task(task_id, **fields)
        if updated is None:
            raise HTTPException(404, "task not found")
        return updated

    @app.get("/api/projects")
    async def list_projects() -> dict:
        return {"projects": store.list_projects()}

    @app.post("/api/projects")
    async def create_project(request: CreateProjectRequest) -> dict:
        name = request.name.strip()
        if not name:
            raise HTTPException(400, "name must not be blank")
        return store.create_project(name)

    @app.delete("/api/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str) -> None:
        if not store.delete_task(task_id):
            raise HTTPException(404, "task not found")
        runtime.evict(task_id)

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_stream(task_id: str) -> dict:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        # 无活动流时幂等 no-op：用户可能在流刚结束的那刻才点下"停止"。
        # 只置位信号，不等流真正退出：消费循环每轮首查信号，≤_STREAM_IDLE_S 内响应，
        # partial + stopped 标记由 stream_reply 的 finally 兜底落库。
        runtime.request_stop(task_id)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/approvals/{approval_id}")
    async def resolve_approval(task_id: str, approval_id: str, request: ApprovalDecisionBody) -> dict:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        # 未知/已解决/不属于该任务的审批 → 404（审批是安全闸门，拒绝伪造调用）。
        if not runtime.resolve_approval(task_id, approval_id, request.approved):
            raise HTTPException(404, "unknown or already-resolved approval")
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/messages")
    async def list_messages(task_id: str) -> dict:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        return {"messages": store.list_messages(task_id)}

    @app.delete("/api/tasks/{task_id}/messages/{message_id}", status_code=204)
    async def delete_turn(task_id: str, message_id: int) -> None:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        # 删除目标轮（user 行 + 其后直到下一 user 前的所有行）；目标非 user 行/不存在 → 404。
        if not store.delete_turn(task_id, message_id):
            raise HTTPException(404, "user message not found")
        # 缓存 agent 的 transcript 仍含被删内容，逐出强制下轮从 DB 重放。
        runtime.evict(task_id)

    @app.post("/api/tasks/{task_id}/messages")
    async def post_message(task_id: str, request: PostMessageRequest) -> StreamingResponse:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")

        async def event_stream():
            async for event in runtime.stream_reply(task_id, request.content):
                yield _sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/tasks/{task_id}/stream")
    async def resume_stream(task_id: str, after: int = Query(0, ge=0)) -> StreamingResponse:
        # 续传：断连/刷新后按 after 补齐错过的 SSE 事件并跟随到本轮结束。
        # 运行已结束/不存在时返回空流（前端据此改为刷新历史）。
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")

        async def event_stream():
            async for event in runtime.stream_reply(task_id, None, after=after):
                yield _sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/tasks/{task_id}/steer")
    async def steer_turn(task_id: str, request: PostMessageRequest) -> dict:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "task not found")
        # 无进行中的运行时 409：前端据此改走普通发送（新起一轮）。
        if not await runtime.steer(task_id, request.content):
            raise HTTPException(409, "no active turn to steer")
        return {"ok": True}

    @app.get("/api/skills")
    async def list_skills() -> dict:
        skills = discover_skills(_SKILLS_ROOT)
        all_names = [s.name for s in skills]
        added = load_my_skills(_MY_SKILLS_PATH, all_names)
        tags = load_tags(_SKILL_TAGS_PATH)
        usage = load_usage(_SKILL_USAGE_PATH)
        return {
            "reachable": True,
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "added": s.name in added,
                    "tags": tags.get(s.name, []),
                    "usage_count": usage.get(s.name, 0),
                }
                for s in skills
            ],
        }

    @app.post("/api/skills/github/scan")
    async def scan_github_skills(request: GithubScanBody) -> dict:
        try:
            validate_repo_url(request.repo_url)
        except GithubImportError as error:
            raise HTTPException(400, str(error))
        try:
            candidates = await scan_github_repo(request.repo_url)
        except GithubImportError as error:
            raise HTTPException(502, str(error))
        return {"candidates": [c.model_dump() for c in candidates]}

    @app.post("/api/skills/github/import")
    async def import_github_skills_route(request: GithubImportBody) -> dict:
        try:
            validate_repo_url(request.repo_url)
        except GithubImportError as error:
            raise HTTPException(400, str(error))
        try:
            imported, skipped = await import_github_skills(
                request.repo_url, request.relative_paths, _SKILLS_ROOT
            )
        except GithubImportError as error:
            raise HTTPException(502, str(error))
        return {"imported": imported, "skipped": [s.model_dump() for s in skipped]}

    @app.post("/api/my-skills/{name}")
    async def add_my_skill_route(name: str) -> dict:
        all_names = [s.name for s in discover_skills(_SKILLS_ROOT)]
        if not add_my_skill(_MY_SKILLS_PATH, all_names, name):
            raise HTTPException(404, f'Unknown skill "{name}".')
        return {"added": True}

    @app.delete("/api/my-skills/{name}")
    async def remove_my_skill_route(name: str) -> dict:
        all_names = [s.name for s in discover_skills(_SKILLS_ROOT)]
        remove_my_skill(_MY_SKILLS_PATH, all_names, name)
        return {"added": False}

    @app.post("/api/skill-upload")
    async def upload_skill_route(file: UploadFile) -> dict:
        content = await file.read()
        try:
            name = extract_uploaded_skill(content, _SKILLS_ROOT)
        except SkillUploadError as error:
            raise HTTPException(422, str(error))
        return {"name": name}

    @app.get("/api/skills/{name}")
    async def get_skill_detail_route(name: str) -> dict:
        skill = next((s for s in discover_skills(_SKILLS_ROOT) if s.name == name), None)
        if skill is None:
            raise HTTPException(404, f'Unknown skill "{name}".')
        all_names = [s.name for s in discover_skills(_SKILLS_ROOT)]
        added = load_my_skills(_MY_SKILLS_PATH, all_names)
        tags = load_tags(_SKILL_TAGS_PATH)
        usage = load_usage(_SKILL_USAGE_PATH)
        # SKILL.md 的正文预览剥掉 frontmatter（裸 YAML 喂 Markdown 渲染器会很难看），
        # 原始 YAML 文本单独留一份给"技能详情"展示。
        files = []
        for relative_path, raw_content in list_skill_files(skill.dir):
            if relative_path == "SKILL.md":
                _, body = parse_frontmatter(skill.content)
                files.append({"path": relative_path, "content": body})
            else:
                files.append({"path": relative_path, "content": raw_content})
        return {
            "name": skill.name,
            "description": skill.description,
            "frontmatter_yaml": extract_frontmatter_text(skill.content),
            "tags": tags.get(skill.name, []),
            "usage_count": usage.get(skill.name, 0),
            "added": skill.name in added,
            "updated_at": skill.updated_at,
            "files": files,
        }

    @app.post("/api/skills/{name}/usage-examples")
    async def suggest_skill_usage_route(name: str, request: SkillUsageExamplesBody) -> dict:
        items = await runtime.suggest_skill_usage(name, request.description)
        return {"items": items}

    @app.get("/api/eval/cases")
    async def list_eval_cases_route() -> dict:
        return {"cases": [c.model_dump() for c in load_eval_cases(eval_cases_path)]}

    @app.post("/api/eval/cases")
    async def create_eval_case_route(request: EvalCaseBody) -> dict:
        case = add_eval_case(eval_cases_path, request.name, request.instruction, request.expected_answer)
        return case.model_dump()

    @app.delete("/api/eval/cases/{case_id}", status_code=204)
    async def delete_eval_case_route(case_id: str) -> None:
        remove_eval_case(eval_cases_path, case_id)

    @app.post("/api/eval/run")
    async def run_eval_route(request: EvalRunBody) -> dict:
        for agent_type in request.agent_types:
            if agent_type not in EVAL_AGENT_TYPES:
                raise HTTPException(422, f"unknown agent_type: {agent_type}")
        all_cases = {c.id: c for c in load_eval_cases(eval_cases_path)}
        cases = [all_cases[cid] for cid in request.case_ids if cid in all_cases]
        # 并发上限：避免 case × agent_type 组合一次性打满上游模型（429/超时）。单条失败不传染。
        semaphore = asyncio.Semaphore(4)

        async def run_one(agent_type: str, case) -> object:
            async with semaphore:
                return await run_case(runtime, agent_type, case)

        results = await asyncio.gather(*[
            run_one(agent_type, case)
            for case in cases
            for agent_type in request.agent_types
        ])
        return store.save_eval_run([r.model_dump() for r in results])

    @app.get("/api/eval/runs")
    async def list_eval_runs_route() -> dict:
        return {"runs": store.list_eval_runs()}

    @app.delete("/api/eval/runs/{run_id}", status_code=204)
    async def delete_eval_run_route(run_id: str) -> None:
        if not store.delete_eval_run(run_id):
            raise HTTPException(404, "eval run not found")

    @app.post("/api/deepresearch/runs")
    async def create_deepresearch_run_route(request: CreateDeepResearchRunBody) -> dict:
        if runtime.search_client is None:
            raise HTTPException(503, "web search is not configured (TAVILY_API_KEY missing)")
        topic = request.topic.strip()
        if not topic:
            raise HTTPException(400, "topic must not be blank")
        run = store.create_deepresearch_run(topic)
        start_live_run(run["id"])
        asyncio.create_task(run_research(store, run["id"], runtime.model_client, runtime.search_client, topic))
        return run

    @app.get("/api/deepresearch/runs")
    async def list_deepresearch_runs_route() -> dict:
        return {"runs": store.list_deepresearch_runs()}

    @app.get("/api/deepresearch/runs/{run_id}")
    async def get_deepresearch_run_route(run_id: str) -> dict:
        run = store.get_deepresearch_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.get("/api/deepresearch/runs/{run_id}/stream")
    async def stream_deepresearch_run_route(run_id: str) -> StreamingResponse:
        async def event_stream():
            async for event in stream_run_events(store, run_id):
                yield _sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.delete("/api/deepresearch/runs/{run_id}", status_code=204)
    async def delete_deepresearch_run_route(run_id: str) -> None:
        run = store.get_deepresearch_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run["status"] == "running":
            raise HTTPException(409, "run is still in progress")
        store.delete_deepresearch_run(run_id)

    @app.post("/api/mcp/servers")
    async def create_mcp_server_route(request: CreateMCPServerBody) -> dict:
        name = request.name.strip()
        if not name:
            raise HTTPException(400, "name must not be blank")
        server_config = MCPServerConfig(
            transport=request.transport, command=request.command, args=request.args, url=request.url
        )
        try:
            tools = await connect_and_list_tools(server_config)
        except MCPConnectionError as error:
            raise HTTPException(502, str(error)) from error
        config = (
            {"command": request.command, "args": request.args}
            if request.transport == "stdio"
            else {"url": request.url}
        )
        cached_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
        ]
        return store.create_mcp_server(
            name=name, transport=request.transport, config=config, cached_tools=cached_tools
        )

    @app.get("/api/mcp/servers")
    async def list_mcp_servers_route() -> dict:
        return {"servers": store.list_mcp_servers()}

    @app.patch("/api/mcp/servers/{server_id}")
    async def update_mcp_server_route(server_id: str, request: UpdateMCPServerBody) -> dict:
        updated = store.set_mcp_server_enabled(server_id, request.enabled)
        if updated is None:
            raise HTTPException(404, "server not found")
        return updated

    @app.post("/api/mcp/servers/{server_id}/refresh")
    async def refresh_mcp_server_route(server_id: str) -> dict:
        existing = store.get_mcp_server(server_id)
        if existing is None:
            raise HTTPException(404, "server not found")
        server_config = MCPServerConfig(transport=existing["transport"], **existing["config"])
        try:
            tools = await connect_and_list_tools(server_config)
        except MCPConnectionError as error:
            return store.update_mcp_server_probe_result(server_id, last_error=str(error))
        cached_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
        ]
        return store.update_mcp_server_probe_result(server_id, last_error=None, cached_tools=cached_tools)

    @app.delete("/api/mcp/servers/{server_id}", status_code=204)
    async def delete_mcp_server_route(server_id: str) -> None:
        if not store.delete_mcp_server(server_id):
            raise HTTPException(404, "server not found")

    return app


app = create_app()
