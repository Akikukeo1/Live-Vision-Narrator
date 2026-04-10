"""
UI Server for Live-Vision-Narrator.

This FastAPI app serves the UI (HTML, CSS, JavaScript) from the `ui/` directory.
It can run independently from the API server in `main.py`.

Run with: python ui.py
or: uvicorn ui:app --reload --port 8001
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import uvicorn
from config import get_settings

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
    """Provide API configuration to UI."""
    settings = get_settings()
    return {
        "api_base_url": f"http://localhost:{settings.api_port}",
        "api_port": settings.api_port,
    }


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("ui:app", host="0.0.0.0", port=settings.ui_port, log_level="info", reload=False)
