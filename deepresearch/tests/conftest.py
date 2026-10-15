import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGES_DIR = _REPO_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from ai.model import ModelClient  # noqa: E402
from core.protocol import Completion  # noqa: E402


@pytest.fixture
def scripted_client():
    """构造一个 ModelClient，acomplete/astream 按顺序吐出脚本里的响应。镜像根项目
    tests/conftest.py 的同名 fixture，只保留 DeepResearch 实际用到的 completions 分支——
    DeepResearch 从不调用 acomplete_with_tools/astream_with_tools，不需要移植那部分。
    """

    def _build(*, completions: Sequence[Completion] = ()) -> ModelClient:
        client = ModelClient(provider="mock")

        if completions:
            queue = list(completions)

            async def fake_acomplete(messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
                return queue.pop(0)

            client.acomplete = fake_acomplete  # type: ignore[method-assign]

            async def fake_astream(messages: list[dict[str, Any]], **kwargs: Any):
                for char in queue.pop(0).text:
                    yield char

            client.astream = fake_astream  # type: ignore[method-assign]

        return client

    return _build
