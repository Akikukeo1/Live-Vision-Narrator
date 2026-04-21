"""
Live-Vision-Narrator の UI サーバ（軽量版）。

静的ファイルを配信し、Go API(8000)へのプロキシを提供します。
ブラウザは常に同一オリジン(8001)へアクセスするため、CORS 問題を回避できます。

実行例（リポジトリルートから）:
    uv run .\\src_py\\ui.py

環境変数:
  API_HOST: API サーバのホスト（デフォルト: localhost）
  API_PORT: API サーバのポート（デフォルト: 8000）
  UI_PORT: UI サーバのポート（デフォルト: 8001）
"""

import os
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Live-Vision-Narrator UI (Light)")

repo_root = Path(__file__).resolve().parent.parent
ui_dir = repo_root / "ui"
models_dir = repo_root / "models"

app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


def backend_base_url() -> str:
    host = os.environ.get("API_HOST", "localhost")
    port = os.environ.get("API_PORT", "8000")
    return f"http://{host}:{port}"


@app.on_event("startup")
async def startup_event():
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))


@app.on_event("shutdown")
async def shutdown_event():
    client = getattr(app.state, "client", None)
    if client is not None:
        await client.aclose()


def _index_response() -> FileResponse | JSONResponse:
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return JSONResponse({"error": "index.html が見つかりません"}, status_code=404)
    return FileResponse(index_path)


@app.get("/", response_class=FileResponse)
async def root():
    return _index_response()


@app.get("/ui", response_class=FileResponse)
async def ui_root():
    return _index_response()


@app.get("/ui/", response_class=FileResponse)
async def ui_root_slash():
    return _index_response()


@app.get("/health")
async def health():
    return {"ok": True, "service": "ui"}


@app.get("/api-config")
async def api_config():
    api_host = os.environ.get("API_HOST", "localhost")
    api_port = int(os.environ.get("API_PORT", "8000"))
    return {"api_base_url": f"http://{api_host}:{api_port}", "api_port": api_port}


@app.post("/generate")
async def proxy_generate(request: Request):
    client: httpx.AsyncClient = app.state.client
    url = backend_base_url() + "/generate"

    try:
        body = await request.json()
    except Exception:
        body = None

    try:
        r = await client.post(url, json=body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception:
        return JSONResponse(status_code=r.status_code, content={"raw": r.text})


@app.post("/generate/stream")
async def proxy_generate_stream(request: Request):
    client: httpx.AsyncClient = app.state.client
    url = backend_base_url() + "/generate/stream"

    try:
        body = await request.json()
    except Exception:
        body = None

    req = client.build_request("POST", url, json=body)
    try:
        res = await client.send(req, stream=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    async def stream_generator():
        try:
            async for chunk in res.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await res.aclose()

    media_type = res.headers.get("content-type", "application/x-ndjson")
    return StreamingResponse(stream_generator(), media_type=media_type, status_code=res.status_code)


@app.post("/session/reset")
async def proxy_session_reset(request: Request):
    client: httpx.AsyncClient = app.state.client
    url = backend_base_url() + "/session/reset"

    try:
        body = await request.json()
    except Exception:
        body = None

    try:
        r = await client.post(url, json=body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception:
        return JSONResponse(status_code=r.status_code, content={"raw": r.text})


@app.post("/session/get")
async def proxy_session_get(request: Request):
    client: httpx.AsyncClient = app.state.client
    url = backend_base_url() + "/session/get"

    try:
        body = await request.json()
    except Exception:
        body = None

    try:
        r = await client.post(url, json=body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception:
        return JSONResponse(status_code=r.status_code, content={"raw": r.text})


if __name__ == "__main__":
    ui_port = int(os.environ.get("UI_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=ui_port, reload=False)
