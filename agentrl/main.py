"""AgentRL：独立的 SFT→GRPO 训练演示服务，不依赖本仓库其他任何包。"""
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
