from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import httpx

app = FastAPI(title="Ollama Proxy (FastAPI)")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_GENERATE_PATH = os.getenv("OLLAMA_GENERATE_PATH", "/api/generate")
WARMUP_MODEL = os.getenv("WARMUP_MODEL")


class GenerateRequest(BaseModel):
    model: str
    prompt: str
    parameters: dict | None = None


client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup_event():
    global client
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    # Optional warmup: trigger a tiny request to load model into memory
    if WARMUP_MODEL and client:
        try:
            await client.post(
                f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}",
                json={"model": WARMUP_MODEL, "prompt": ""},
                timeout=5.0,
            )
        except Exception:
            # Non-fatal; warmup best-effort only
            pass


@app.on_event("shutdown")
async def shutdown_event():
    global client
    if client is not None:
        await client.aclose()


@app.get("/health")
async def health():
    # Check minimal connectivity to Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(OLLAMA_URL)
            return {"ok": True, "ollama_status_code": r.status_code}
    except Exception:
        return {"ok": False, "ollama_url": OLLAMA_URL}


@app.get("/")
async def root():
    return {"ok": True, "endpoints": ["/health", "/generate"]}


@app.post("/generate")
async def generate(req: GenerateRequest):
    global client
    if client is None:
        raise HTTPException(status_code=503, detail="Service not started")

    payload: dict = {"model": req.model, "prompt": req.prompt}
    if req.parameters:
        payload.update(req.parameters)

    try:
        r = await client.post(f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    # Return whatever Ollama returns (assumed JSON)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
def main():
    print("Hello from live-vision-narrator!")


if __name__ == "__main__":
    main()
