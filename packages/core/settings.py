from pydantic import BaseModel


class RuntimeSettings(BaseModel):
    temperature: float = 0.7
    max_tokens: int | None = None
    debug: bool = False
    log_level: str = "INFO"
    callback_timeout_seconds: float = 5.0
