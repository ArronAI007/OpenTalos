from pydantic import BaseModel


class ExtractRequest(BaseModel):
    tenant_id: str
    session_id: str
    run_id: str
    user_message: str
    assistant_reply: str


class ConsolidateRequest(BaseModel):
    tenant_id: str


class SummaryEntry(BaseModel):
    type: str
    title: str


class SummaryResponse(BaseModel):
    entries: list[SummaryEntry]


class SearchRequest(BaseModel):
    tenant_id: str
    query: str


class SearchResultItem(BaseModel):
    key: str
    value: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class TenantsWithPendingResponse(BaseModel):
    tenant_ids: list[str]
