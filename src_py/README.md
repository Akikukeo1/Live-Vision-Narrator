# src_py

現在、このAPIはPythonからGoへ移行しています。Python製のAPIは廃止されます。

ただし、abliterator/では、ライブラリなどの関係でPythonコードも必要なため、src_pyの一部は当面維持されます。特に、UIサーバ（ui.py）はPythonで運用を続ける予定です。

## 移行状況

abliterator/: ./Hereticを使用する方向へ変更

client_test.py: 現在、現役のデバッガ用のテストコードです。これがCIで実行される事はありません。
config.py: 完了 → config.go に移行
main.py: 完了 → main.go, text_processor.go, ollama_client.go に移行
ui.py: **当面 Python で維持**。LAN / モバイルから手軽にアクセスできるシンプルな UI サーバ。

## UI サーバについて（ui.py）

### 概要

`ui.py` は静的ファイル（`ui/` ディレクトリ）の配信と、Go API へのプロキシを行う軽量な FastAPI アプリです。

- **静的配信**: `ui/index.html`, `ui/main.js`, `ui/style.css` を `/static` 経由で提供（ブラウザ側から見える）。
- **UI→API プロキシ**: `/generate`, `/generate/stream`, `/session/get`, `/session/reset` を Go API 側へ中継。
- **API メタ情報**: `/api-config`（API ホスト・ポート情報）、`/health` を提供。
- **システムプロファイル**: `/system-profiles`, `/system-profiles/{name}` でローカル `Modelfile*` から選択・取得。

### 起動方法

```bash
# リポジトリルートから（API サーバも起動している前提）
python -m uvicorn src_py.ui:app --host 0.0.0.0 --port 8001

# 環境変数で API アドレスを指定する場合
export API_HOST=192.168.0.10
export API_PORT=8000
python -m uvicorn src_py.ui:app --host 0.0.0.0 --port 8001
```

ブラウザで `http://<LAN_IP>:8001` にアクセスして UI を利用できます。

### 特徴

- **LAN / モバイル対応**: スマートフォンなど複数端末から同一LAN内の PC の API にアクセス可能。
- **コンテキスト管理**: セッション ID ごとに対話履歴を保持（`/session/get`, `/session/reset`）。
- **Thinking 表示**: モデルの推論ステップを表示・保存可能（`reveal_thoughts`, `save_inner`）。
- **システムプロファイル切り替え**: ローカルファイル（`Modelfile`, `Modelfile.detailed` 等）から システムプロンプトを選択可能（`/system-profiles`）。

### API ドキュメント

詳細は [UI_API.md](UI_API.md) を参照してください。

---

## 今後の展開

- `ui.py` は Python で主に運用を続けます（UI 処理はパフォーマンス要件が低いため）。
- `src-go` へ統合する際は、同等の静的配信と `/system-profiles` ロジックを Go 側へ実装する予定。
- 必要に応じて React / Vue 等フロントエンドフレームワークへの移行も検討予定です。
