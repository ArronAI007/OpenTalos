from fastapi import FastAPI

app = FastAPI(title="OpenTalos Skill Service")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
