from pydantic import BaseModel


class SkillSummary(BaseModel):
    name: str
    description: str
    added: bool
    tags: list[str]
    usage_count: int


class SkillListResponse(BaseModel):
    skills: list[SkillSummary]


class SkillDetailResponse(BaseModel):
    name: str
    content: str


class GithubSkillCandidate(BaseModel):
    relative_path: str
    name: str
    description: str


class GithubImportSkipped(BaseModel):
    name: str
    reason: str


class GithubScanRequest(BaseModel):
    repo_url: str


class GithubScanResponse(BaseModel):
    candidates: list[GithubSkillCandidate]


class GithubImportRequest(BaseModel):
    repo_url: str
    relative_paths: list[str]


class GithubImportResponse(BaseModel):
    imported: list[str]
    skipped: list[GithubImportSkipped]


class SkillFile(BaseModel):
    path: str
    content: str | None


class SkillPreview(BaseModel):
    name: str
    description: str
    frontmatter_yaml: str | None
    tags: list[str]
    usage_count: int
    added: bool
    updated_at: str
    files: list[SkillFile]
