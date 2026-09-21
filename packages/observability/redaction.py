import re
from typing import Any

_API_KEY_PATTERN = re.compile(r"sk-[a-zA-Z0-9]+")
_BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+[a-zA-Z0-9_\-]+")
_HOME_DIR_PATTERN = re.compile(r"(/Users/|/home/|C:\\Users\\)[^/\\]+")


def redact(value: Any) -> Any:
    """递归脱敏：API key、Bearer token、用户主目录路径下的用户名。

    Bearer 正则要先跑：常见的 `Bearer sk-xxx` 头部本身也会命中 API key 正则，两个正则
    谁先跑都会命中，但顺序反过来（API key 先跑）会把同一段文本命中两次、叠加出双倍星号。
    """
    if isinstance(value, str):
        value = _BEARER_TOKEN_PATTERN.sub("Bearer ***", value)
        value = _API_KEY_PATTERN.sub("sk-***", value)
        return _HOME_DIR_PATTERN.sub(r"\1***", value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
