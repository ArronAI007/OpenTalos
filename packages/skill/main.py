import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import docker
from fastapi import FastAPI, HTTPException

from skill.discovery import discover_skills
from skill.models import (
    RunScriptRequest,
    RunScriptResponse,
    SkillDetailResponse,
    SkillListResponse,
    SkillSummary,
)
from skill.sandbox import PathValidationError, resolve_interpreter, resolve_script_path, run_sandboxed_script

DEFAULT_MAX_CONCURRENCY = 4
# packages/skill/main.py -> packages/skill -> packages -> 仓库根目录
SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"

_docker_client: docker.DockerClient | None = None
_semaphore: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _docker_client, _semaphore
    _docker_client = docker.from_env()
    max_concurrency = int(os.environ.get("SANDBOX_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY))
    _semaphore = asyncio.Semaphore(max_concurrency)
    yield
    _docker_client.close()


app = FastAPI(title="OpenTalos Skill Service", lifespan=lifespan)


def get_docker_client() -> docker.DockerClient:
    assert _docker_client is not None, "docker client not initialized — app startup hasn't run"
    return _docker_client


def get_semaphore() -> asyncio.Semaphore:
    assert _semaphore is not None, "semaphore not initialized — app startup hasn't run"
    return _semaphore


def _find_skill(name: str):
    skills = discover_skills(SKILLS_ROOT)
    return next((s for s in skills if s.name == name), None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/skills", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    skills = discover_skills(SKILLS_ROOT)
    return SkillListResponse(skills=[SkillSummary(name=s.name, description=s.description) for s in skills])


@app.get("/skills/{name}", response_model=SkillDetailResponse)
async def get_skill(name: str) -> SkillDetailResponse:
    skill = _find_skill(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f'Unknown skill "{name}".')
    return SkillDetailResponse(name=skill.name, content=skill.content)


@app.post("/skills/{name}/run-script", response_model=RunScriptResponse)
async def run_script(name: str, request: RunScriptRequest) -> RunScriptResponse:
    skill = _find_skill(name)
    if skill is None:
        raise HTTPException(status_code=422, detail=f'Unknown skill "{name}".')

    try:
        script_path = resolve_script_path(skill.dir, request.script_relative_path)
        resolve_interpreter(script_path)
    except PathValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    async with get_semaphore():
        result = await run_sandboxed_script(
            get_docker_client(), script_path, request.args, request.input_text, request.timeout_ms
        )
    return RunScriptResponse(
        stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code, timed_out=result.timed_out
    )
