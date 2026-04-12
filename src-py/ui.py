"""
Live-Vision-Narrator の UI サーバ。

この FastAPI アプリは `ui/` ディレクトリから HTML/CSS/JS を配信します。
`main.py` の API サーバとは独立して実行可能です。

実行例: python ui.py
または: uvicorn ui:app --reload --port 8001

# TODO: UI 配信周りのエラーハンドリングを確認してください。
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import uvicorn
from config import get_settings
import logging

# ログ設定のために早期に設定を読み込む
settings = get_settings()
# UI サーバ用のログ設定
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
    """メインの UI HTML を返します。"""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html が見つかりません"}
    return FileResponse(index_path)


@app.get("/ui", response_class=FileResponse)
async def ui():
    """メイン UI HTML を返す別ルート。"""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html が見つかりません"}
    return FileResponse(index_path)


@app.get("/health")
async def health():
    """Simple health check."""
    return {"ok": True, "service": "ui"}


@app.get("/api-config")
async def api_config():
    """UI に渡す API 設定を返します。

    ブラウザから接続するため `api_host` / `api_port` を使用します。
    """
    settings = get_settings()
    return {
        "api_base_url": f"http://{settings.api_host}:{settings.api_port}",
        "api_port": settings.api_port,
    }


if __name__ == "__main__":
    uvicorn.run("ui:app", host=settings.ui_ip, port=settings.ui_port, log_level=settings.log_level.lower(), reload=False)
