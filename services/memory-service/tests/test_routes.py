import pytest
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from app.main import app
from db.bulk import NewMemory, insert_raw_memory, upsert_memories


@pytest.fixture
def client(pg_pool: AsyncConnectionPool, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", pg_pool.conninfo)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_extract_returns_204(client: TestClient) -> None:
    response = client.post(
        "/memory/extract",
        json={
            "tenant_id": "tenant-route-extract",
            "session_id": "s1",
            "run_id": "run-1",
            "user_message": "hi",
            "assistant_reply": "hello",
        },
    )
    assert response.status_code == 204


def test_extract_returns_422_on_missing_field(client: TestClient) -> None:
    response = client.post("/memory/extract", json={"tenant_id": "t"})
    assert response.status_code == 422


def test_consolidate_returns_204(client: TestClient) -> None:
    response = client.post("/memory/consolidate", json={"tenant_id": "tenant-route-consolidate"})
    assert response.status_code == 204


async def test_summary_returns_entries(client: TestClient, pg_pool: AsyncConnectionPool) -> None:
    await upsert_memories(pg_pool, "tenant-route-summary", [NewMemory(type="profile", title="职业", content="工程师")], [])
    response = client.get("/memory/summary", params={"tenant_id": "tenant-route-summary"})
    assert response.status_code == 200
    assert response.json() == {"entries": [{"type": "profile", "title": "职业"}]}


async def test_search_returns_matching_results(client: TestClient, pg_pool: AsyncConnectionPool) -> None:
    await upsert_memories(pg_pool, "tenant-route-search", [NewMemory(type="profile", title="职业", content="后端工程师")], [])
    response = client.post("/memory/search", json={"tenant_id": "tenant-route-search", "query": "工程师"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"key": "职业", "value": "后端工程师", "score": 0.0}]


async def test_tenants_with_pending_only_returns_tenants_with_rows(client: TestClient, pg_pool: AsyncConnectionPool) -> None:
    await insert_raw_memory(pg_pool, "tenant-route-pending", "s1", "run-1", "some fact")
    response = client.get(
        "/memory/tenants-with-pending", params={"tenant_ids": "tenant-route-pending,tenant-route-idle"}
    )
    assert response.status_code == 200
    assert response.json() == {"tenant_ids": ["tenant-route-pending"]}
