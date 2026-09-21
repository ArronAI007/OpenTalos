import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Response
from psycopg_pool import AsyncConnectionPool

# 跟 apps/worker/src/index.ts 一样，从仓库根目录的 .env 读配置——只补齐还没设置的变量，不覆盖
# 已经存在的 process env（override=False 是 python-dotenv 的默认行为，跟 Node 的 dotenv 一致）。
load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env", override=False)

from app.consolidate import consolidate_memories_for_tenant  # noqa: E402
from app.extraction import extract_memory  # noqa: E402
from app.models import (  # noqa: E402
    ConsolidateRequest,
    ExtractRequest,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SummaryEntry,
    SummaryResponse,
    TenantsWithPendingResponse,
)
from db.bulk import list_memories_for_tenant, list_tenants_with_pending, search_memories  # noqa: E402
from providers.base import TextCompletionProvider  # noqa: E402
from providers.factory import create_provider_from_env  # noqa: E402

_pool: AsyncConnectionPool | None = None
_provider: TextCompletionProvider | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _provider
    _pool = AsyncConnectionPool(os.environ["DATABASE_URL"], open=False)
    await _pool.open()
    _provider = create_provider_from_env()
    yield
    await _pool.close()


app = FastAPI(title="OpenTalos Memory Service", lifespan=lifespan)


def get_pool() -> AsyncConnectionPool:
    assert _pool is not None, "pool not initialized — app startup hasn't run"
    return _pool


def get_provider() -> TextCompletionProvider:
    assert _provider is not None, "provider not initialized — app startup hasn't run"
    return _provider


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/memory/extract", status_code=204)
async def extract(request: ExtractRequest) -> Response:
    await extract_memory(
        get_pool(),
        get_provider(),
        request.tenant_id,
        request.session_id,
        request.run_id,
        request.user_message,
        request.assistant_reply,
    )
    return Response(status_code=204)


@app.post("/memory/consolidate", status_code=204)
async def consolidate(request: ConsolidateRequest) -> Response:
    await consolidate_memories_for_tenant(get_pool(), get_provider(), request.tenant_id)
    return Response(status_code=204)


@app.get("/memory/summary", response_model=SummaryResponse)
async def summary(tenant_id: str = Query(...)) -> SummaryResponse:
    entries = await list_memories_for_tenant(get_pool(), tenant_id)
    return SummaryResponse(entries=[SummaryEntry(type=e.type, title=e.title) for e in entries])


@app.post("/memory/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    results = await search_memories(get_pool(), request.tenant_id, request.query)
    return SearchResponse(results=[SearchResultItem(**r) for r in results])


@app.get("/memory/tenants-with-pending", response_model=TenantsWithPendingResponse)
async def tenants_with_pending(tenant_ids: str = Query(...)) -> TenantsWithPendingResponse:
    ids = [t for t in tenant_ids.split(",") if t]
    result = await list_tenants_with_pending(get_pool(), ids)
    return TenantsWithPendingResponse(tenant_ids=result)
