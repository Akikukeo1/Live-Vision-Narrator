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
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import uvicorn

app = FastAPI(title="Live-Vision-Narrator UI (Light)")

# 同じディレクトリ内の HTML/CSS/JS を静的ファイルとして配信
ui_dir = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """メイン UI HTML を返します。"""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return JSONResponse({"error": "index.html が見つかりません"}, status_code=404)
    return FileResponse(index_path)


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


if __name__ == "__main__":
    ui_port = int(os.environ.get("UI_PORT", "8001"))
    uvicorn.run("ui:app", host="0.0.0.0", port=ui_port, reload=False)
