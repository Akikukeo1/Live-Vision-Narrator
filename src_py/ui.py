"""
Live-Vision-Narrator の UI サーバ（軽量版）。

このシンプルな FastAPI アプリは `ui/` ディレクトリから静的ファイルを配信し、
API 設定と基本的なヘルスチェックを提供します。

実行例（リポジトリルートから）:
  python -m uvicorn src-py.ui:app --host 0.0.0.0 --port 8001

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

# ui ディレクトリへの堅牢なパス解決（リポジトリルート/ui を指す）
ui_dir = Path(__file__).resolve().parent.parent / "ui"
if not ui_dir.exists():
    # 互換性のため、同フォルダ内内の ui も試す
    alt = Path(__file__).resolve().parent / "ui"
    if alt.exists():
        ui_dir = alt

# 静的ファイル（CSS, JS）をマウント
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
    # モジュール名でのインポートは環境によって失敗するため
    # 直接 app オブジェクトを渡して起動する（ローカル実行向け）
    uvicorn.run(app, host="0.0.0.0", port=ui_port, reload=False)
