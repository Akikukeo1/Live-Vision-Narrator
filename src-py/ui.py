"""
Live-Vision-NarratorのUIサーバー。

このFastAPIアプリケーションは、`ui/`ディレクトリからUI（HTML、CSS、JavaScript）を提供します。
APIサーバー（`main.py`）とは独立して動作可能です。

以下のコマンドで実行できます:
    python ui.py
または:
    uvicorn ui:app --reload --port 8001
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import uvicorn
from config import get_settings
import logging

# Load settings early so logging can be configured
settings = get_settings()
# Configure logging for UI server
log_level_val = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(level=log_level_val)
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx"):
    try:
        logging.getLogger(logger_name).setLevel(log_level_val)
    except Exception:
        pass

app = FastAPI(title="Live-Vision-Narrator UI")

# Mount static files (CSS, JS, etc.)
ui_dir = Path(__file__).parent / "ui"
app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """Serve the main UI HTML."""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html not found"}
    return FileResponse(index_path)


@app.get("/ui", response_class=FileResponse)
async def ui():
    """Serve the main UI HTML (alternative route)."""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html not found"}
    return FileResponse(index_path)


@app.get("/health")
async def health():
    """Simple health check."""
    return {"ok": True, "service": "ui"}


@app.get("/api-config")
async def api_config():
    """Provide API configuration to UI.

    Uses api_host (browser-accessible) instead of host_ip (server binding).
    """
    settings = get_settings()
    return {
        "api_base_url": f"http://{settings.api_host}:{settings.api_port}",
        "api_port": settings.api_port,
    }


if __name__ == "__main__":
    uvicorn.run("ui:app", host=settings.ui_ip, port=settings.ui_port, log_level=settings.log_level.lower(), reload=False)
