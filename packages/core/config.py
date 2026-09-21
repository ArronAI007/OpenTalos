from pydantic import BaseModel


class Config(BaseModel):
    temperature: float = 0.7
    max_tokens: int | None = None
    debug: bool = False
    log_level: str = "INFO"
    hook_timeout_seconds: float = 5.0
