"""长期记忆的 embedding 客户端：把文本转成向量，供 LongTermMemory 做语义检索。

复用 openai SDK（和 core/model.py 的 OpenAICompatibleBackend 同构，只是调 embeddings 而非
chat completions）。构造时**不**校验配置是否齐全——ChatStore 任何时候都会无条件构造一个
EmbeddingClient，即使长期记忆功能关闭（MEMORY_ENABLED 默认关闭）也不该因为没配 EMBED_* 就报错；
只有真正调用 embed() 且配置缺失时才报错。同理，底层的 AsyncOpenAI 客户端也要推迟到 embed()
内部才构造——AsyncOpenAI(api_key=None) 本身会立即抛错，不能放进 __init__。
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class EmbeddingClient:
    def __init__(
        self, *, model_name: str | None = None, api_key: str | None = None, base_url: str | None = None
    ) -> None:
        self.model_name = model_name or os.getenv("EMBED_MODEL_NAME")
        self.api_key = api_key or os.getenv("EMBED_API_KEY")
        self.base_url = base_url or os.getenv("EMBED_BASE_URL")
        self._client: AsyncOpenAI | None = None

    async def embed(self, text: str) -> list[float]:
        if not self.model_name or not self.api_key:
            raise RuntimeError("EmbeddingClient 缺少配置：需要 EMBED_MODEL_NAME 和 EMBED_API_KEY")
        if self._client is None:
            client_kwargs: dict[str, str] = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**client_kwargs)
        response = await self._client.embeddings.create(model=self.model_name, input=text)
        return response.data[0].embedding
