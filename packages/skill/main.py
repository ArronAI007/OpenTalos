import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile

from skill.discovery import discover_skills
from skill.execution import PathValidationError, execute_script, resolve_interpreter, resolve_script_path
from skill.github_import import GithubImportError, import_github_skills, scan_github_repo, validate_repo_url
from skill.my_skills import add_my_skill, load_my_skills, remove_my_skill
from skill.skill_tags import load_tags
from skill.skill_upload import SkillUploadError, extract_uploaded_skill
from skill.skill_usage import increment_usage, load_usage
from skill.models import (
    GithubImportRequest,
    GithubImportResponse,
    GithubScanRequest,
    GithubScanResponse,
    RunScriptRequest,
    RunScriptResponse,
    SkillDetailResponse,
    SkillListResponse,
    SkillSummary,
)

DEFAULT_MAX_CONCURRENCY = 4
# packages/skill/main.py -> packages/skill -> packages -> 仓库根目录
SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"
MY_SKILLS_PATH = Path(__file__).resolve().parent.parent.parent / ".data" / "my_skills.json"
SKILL_TAGS_PATH = Path(__file__).resolve().parent.parent.parent / ".data" / "skill_tags.json"
SKILL_USAGE_PATH = Path(__file__).resolve().parent.parent.parent / ".data" / "skill_usage.json"

_semaphore: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore
    max_concurrency = int(os.environ.get("SKILL_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY))
    _semaphore = asyncio.Semaphore(max_concurrency)
    yield


app = FastAPI(title="OpenTalos Skill Service", lifespan=lifespan)


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
    my_skills = load_my_skills(MY_SKILLS_PATH, [s.name for s in skills])
    tags_by_name = load_tags(SKILL_TAGS_PATH)
    usage_by_name = load_usage(SKILL_USAGE_PATH)
    return SkillListResponse(skills=[
        SkillSummary(
            name=s.name, description=s.description, added=s.name in my_skills,
            tags=tags_by_name.get(s.name, []), usage_count=usage_by_name.get(s.name, 0),
        )
        for s in skills
    ])


@app.get("/skills/{name}", response_model=SkillDetailResponse)
async def get_skill(name: str) -> SkillDetailResponse:
    skill = _find_skill(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f'Unknown skill "{name}".')
    all_names = [s.name for s in discover_skills(SKILLS_ROOT)]
    if name not in load_my_skills(MY_SKILLS_PATH, all_names):
        raise HTTPException(status_code=404, detail=f'Unknown skill "{name}".')
    return SkillDetailResponse(name=skill.name, content=skill.content)


@app.post("/skills/{name}/run-script", response_model=RunScriptResponse)
async def run_script(name: str, request: RunScriptRequest) -> RunScriptResponse:
    skill = _find_skill(name)
    if skill is None:
        raise HTTPException(status_code=422, detail=f'Unknown skill "{name}".')
    all_names = [s.name for s in discover_skills(SKILLS_ROOT)]
    if name not in load_my_skills(MY_SKILLS_PATH, all_names):
        raise HTTPException(status_code=422, detail=f'Unknown skill "{name}".')

    try:
        script_path = resolve_script_path(skill.dir, request.script_relative_path)
        resolve_interpreter(script_path)
    except PathValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # 信号量只约束并发子进程数——脚本在宿主机直跑（沙箱后续专门重做），没有别的资源闸口。
    async with get_semaphore():
        result = await execute_script(script_path, request.args, request.input_text, request.timeout_ms)
    increment_usage(SKILL_USAGE_PATH, name)
    return RunScriptResponse(
        stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code, timed_out=result.timed_out
    )


@app.post("/github-import/scan", response_model=GithubScanResponse)
async def scan_github(request: GithubScanRequest) -> GithubScanResponse:
    try:
        validate_repo_url(request.repo_url)
    except GithubImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        candidates = await scan_github_repo(request.repo_url)
    except GithubImportError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return GithubScanResponse(candidates=candidates)


@app.post("/github-import/import", response_model=GithubImportResponse)
async def import_github(request: GithubImportRequest) -> GithubImportResponse:
    try:
        validate_repo_url(request.repo_url)
    except GithubImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        imported, skipped = await import_github_skills(request.repo_url, request.relative_paths, SKILLS_ROOT)
    except GithubImportError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return GithubImportResponse(imported=imported, skipped=skipped)


@app.post("/my-skills/{name}")
async def add_my_skill_route(name: str) -> dict:
    all_names = [s.name for s in discover_skills(SKILLS_ROOT)]
    added = add_my_skill(MY_SKILLS_PATH, all_names, name)
    if not added:
        raise HTTPException(status_code=404, detail=f'Unknown skill "{name}".')
    return {"added": True}


@app.delete("/my-skills/{name}")
async def remove_my_skill_route(name: str) -> dict:
    all_names = [s.name for s in discover_skills(SKILLS_ROOT)]
    remove_my_skill(MY_SKILLS_PATH, all_names, name)
    return {"added": False}


@app.post("/skill-upload")
async def upload_skill(file: UploadFile) -> dict:
    content = await file.read()
    try:
        name = extract_uploaded_skill(content, SKILLS_ROOT)
    except SkillUploadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"name": name}
