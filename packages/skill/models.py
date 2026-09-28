from pydantic import BaseModel, field_validator

MAX_INPUT_TEXT_BYTES = 65_536


class RunScriptRequest(BaseModel):
    script_relative_path: str
    args: list[str] = []
    input_text: str | None = None
    timeout_ms: int = 10_000

    @field_validator("input_text")
    @classmethod
    def validate_input_text_size(cls, value: str | None) -> str | None:
        if value is not None:
            byte_length = len(value.encode("utf-8"))
            if byte_length > MAX_INPUT_TEXT_BYTES:
                raise ValueError(
                    f"Skill input text is too large: {byte_length} bytes exceeds "
                    f"the {MAX_INPUT_TEXT_BYTES}-byte limit. Provide a smaller input."
                )
        return value


class RunScriptResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


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
