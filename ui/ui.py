"""
Live-Vision-Narrator UI サーバ（軽量版）。

静的ファイル（HTML/CSS/JS）の配信と API メタ設定を提供します。
Go の API サーバ（8000）と連携して、LAN / モバイルからアクセス可能な UI を提供します。

実行例（ui/ ディレクトリから）:
  python ui.py
  あるいは
  python -m uvicorn ui:app --host 0.0.0.0 --port 8001

環境変数:
  API_HOST: API サーバのホスト（デフォルト: localhost）
  API_PORT: API サーバのポート（デフォルト: 8000）
  UI_PORT: UI サーバのポート（デフォルト: 8001）
"""

import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pathlib import Path
import uvicorn
import httpx

app = FastAPI(title="Live-Vision-Narrator UI (Light)")

repo_root = Path(__file__).resolve().parent.parent
models_dir = repo_root / "models"

# 同じディレクトリ内の HTML/CSS/JS を静的ファイルとして配信
ui_dir = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


def available_system_profiles() -> dict:
    profiles = {}

    default_file = models_dir / "Modelfile"
    detailed_file = models_dir / "Modelfile.detailed"

    if default_file.exists():
        profiles["default"] = {"name": "default", "source": str(default_file.relative_to(repo_root))}
    if detailed_file.exists():
        profiles["detailed"] = {"name": "detailed", "source": str(detailed_file.relative_to(repo_root))}

    for f in repo_root.glob("Modelfile-*"):
        suffix = f.name.replace("Modelfile-", "", 1).strip()
        if suffix:
            profiles[suffix] = {"name": suffix, "source": f.name}

    return profiles


def resolve_system_profile_file(name: str) -> Path | None:
    if name == "default":
        p = models_dir / "Modelfile"
        return p if p.exists() else None
    if name == "detailed":
        p = models_dir / "Modelfile.detailed"
        return p if p.exists() else None

    candidate = repo_root / f"Modelfile-{name}"
    if candidate.exists():
        return candidate
    return None


def _index_response() -> FileResponse | JSONResponse:
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return JSONResponse({"error": "index.html が見つかりません"}, status_code=404)
    return FileResponse(index_path)


@app.get("/", response_class=FileResponse)
async def root():
    """メイン UI HTML を返します。"""
    return _index_response()


@app.get("/ui", response_class=FileResponse)
async def ui_root():
    return _index_response()


@app.get("/ui/", response_class=FileResponse)
async def ui_root_slash():
    return _index_response()


@app.get("/health")
async def health():
    """ヘルスチェック。"""
    return {"ok": True, "service": "ui"}


@app.get("/api-config")
async def api_config():
    """UI に渡す API 設定を返します。

    環境変数を優先し、未設定ならデフォルト値を使用します。
    """
    api_host = os.environ.get("API_HOST", "localhost")
    api_port = int(os.environ.get("API_PORT", "8000"))
    return {"api_base_url": f"http://{api_host}:{api_port}", "api_port": api_port}


@app.on_event("startup")
async def startup_event():
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))


@app.on_event("shutdown")
async def shutdown_event():
    client = getattr(app.state, "client", None)
    if client is not None:
        await client.aclose()


def backend_base_url() -> str:
    host = os.environ.get("API_HOST", "localhost")
    port = os.environ.get("API_PORT", "8000")
    return f"http://{host}:{port}"


@app.get("/system-profiles")
async def proxy_system_profiles():
    return {"profiles": available_system_profiles()}


@app.get("/system-profiles/{name}")
async def proxy_system_profile_get(name: str):
    profile_file = resolve_system_profile_file(name)
    if profile_file is None:
        raise HTTPException(status_code=404, detail=f"system profile not found: {name}")

    try:
        content = profile_file.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to read profile: {e}")

    return {
        "name": name,
        "source": str(profile_file.relative_to(repo_root)),
        "content": content,
    }


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
    uvicorn.run("ui:app", host="0.0.0.0", port=ui_port, reload=False)
