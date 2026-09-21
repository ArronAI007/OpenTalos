from fastapi import FastAPI

app = FastAPI(title="OpenTalos Memory Service")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
