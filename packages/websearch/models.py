from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class ExtractedPage(BaseModel):
    url: str
    raw_content: str


class FailedExtraction(BaseModel):
    url: str
    error: str


class ExtractResponse(BaseModel):
    results: list[ExtractedPage]
    failed_results: list[FailedExtraction]
