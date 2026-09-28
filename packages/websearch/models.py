from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
