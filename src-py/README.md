# src-py

現在、このAPIはPythonからGoへ移行しています。Pythonは廃止されます。src-goが新しいコードベースで、src-pyは古いコードベースです。src-pyは移行期間中に参照用として残されますが、新しい機能はsrc-goに追加されます。src-pyのコードは将来的に削除される予定です。

## 移行状況

client_test.py: 現在、現役のデバッガ用のテストコードです。これがCIで実行される事はありません。
config.py: 完了 → config.go に移行
main.py: 完了 → main.go, text_processor.go, ollama_client.go に移行
ui.py: **当面 Python で維持**。LAN / モバイルから手軽にアクセスできるシンプルな UI サーバ。将来的には `src-go` へ統合予定です。

## UI サーバについて（ui.py）

### 概要

`ui.py` は静的ファイル（`ui/` ディレクトリ）の配信と、API メタ設定の提供を行う軽量な FastAPI アプリです。

- **静的配信**: `ui/index.html`, `ui/main.js`, `ui/style.css` を `/static` 経由で提供（ブラウザ側から見える）。
- **API ゲートウェイ**: `/api-config`（API ホスト・ポート情報）、`/health` を提供。

### 起動方法

```bash
# リポジトリルートから（API サーバも起動している前提）
python -m uvicorn src-py.ui:app --host 0.0.0.0 --port 8001

# 環境変数で API アドレスを指定する場合
export API_HOST=192.168.0.10
export API_PORT=8000
python -m uvicorn src-py.ui:app --host 0.0.0.0 --port 8001
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
