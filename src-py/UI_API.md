# Live-Vision-Narrator UI API ドキュメント

## 概要

このドキュメントは、`src-py/main.py` (API サーバ) の UI 向けエンドポイント仕様をまとめます。  
UI（`ui/index.html`, `ui/main.js`）は、このプロトコルに従ってリクエストを送信します。

---

## エンドポイント一覧

### `/generate` (POST)
**説明**: プロンプトを送信し、非ストリーミングで応答を受け取ります。

**リクエスト**:
```json
{
  "model": "live-narrator",
  "prompt": "こんにちは",
  "parameters": {
    "think": true,
    "reveal_thoughts": true,
    "save_inner": false,
    "inner_detail": "short",
    "system_profile": "default",
    "system_override": ""
  },
  "session_id": "default"
}
```

**レスポンス**:
```json
{
  "response": "こんにちは。お役に立てることがあればお知らせください。",
  "thinking": "ユーザーの挨拶に対して丁寧に返答する。",
  "tokens": {
    "prompt_tokens": 10,
    "response_tokens": 25,
    "total_tokens": 35
  },
  "elapsed_ms": 1234.5,
  "context": [...]
}
```

---

### `/generate/stream` (POST)
**説明**: プロンプトをストリーミングで送信します。応答は NDJSON 形式で逐次返却されます。

**リクエスト**: `/generate` と同じ。

**レスポンス**: NDJSON（改行区切り JSON）
```
{"elapsed_ms": 45.2}
{"response": "こん"}
{"response": "にちは"}
{"response": "。"}
{"thinking": "ユーザーの挨拶に対して..."}
{"done": true, "tokens": {"prompt_tokens": 10, "response_tokens": 25, "total_tokens": 35}}
```

**ストリーミング仕様**:
- 最初の行は `{"elapsed_ms": <number>}`（サーバから応答開始までの時間）。
- 以降、各チャンクは JSON オブジェクト。
- `response` フィールド: 生成テキスト（一部）。
- `thinking` フィールド: 内部思考（`reveal_thoughts` 指定時のみ）。
- 最終行は `{"done": true, "tokens": {...}}`。

---

### `/session/get` (POST)
**説明**: セッションのコンテキストと対話履歴を取得します。

**リクエスト**:
```json
{
  "session_id": "default"
}
```

**レスポンス**:
```json
{
  "ok": true,
  "session_id": "default",
  "has_context": true,
  "context_length": 128,
  "history_length": 4,
  "history": [
    {"role": "user", "text": "こんにちは"},
    {"role": "assistant", "text": "こんにちは。お役に立てることがあればお知らせください。"},
    {"role": "user", "text": "次のプロンプト"},
    {"role": "assistant", "text": "..."}
  ],
  "context": [123, 456, ...]
}
```

---

### `/session/reset` (POST)
**説明**: セッションのコンテキストと履歴をクリアします。

**リクエスト**:
```json
{
  "session_id": "default"
}
```

**レスポンス**:
```json
{
  "ok": true,
  "session_id": "default",
  "reset": true
}
```

---

### `/system-profiles` (GET)
**説明**: 利用可能なシステムプロファイル（ローカル設定ファイル）の一覧を返します。

**リクエスト**: パラメータなし

**レスポンス**:
```json
{
  "ok": true,
  "profiles": {
    "default": {
      "name": "default",
      "path": "/path/to/Modelfile",
      "exists": true
    },
    "detailed": {
      "name": "detailed",
      "path": "/path/to/Modelfile.detailed",
      "exists": true
    }
  },
  "count": 2
}
```

---

### `/system-profiles/{name}` (GET)
**説明**: 指定したシステムプロファイルの内容を取得します。

**リクエスト**: `/system-profiles/default` など

**レスポンス**:
```json
{
  "ok": true,
  "name": "default",
  "content": "あなたは優秀なアシスタントです。\n..."
}
```

**エラー**: プロファイルが見つからない場合は 404 を返す。

---

### `/models` (GET)
**説明**: Ollama から取得可能なモデル一覧を返します。

**リクエスト**: パラメータなし

**レスポンス**: Ollama `/api/tags` の応答フォーマット（モデルリスト）

---

### `/health` (GET)
**説明**: サーバのヘルスチェック。

**レスポンス**:
```json
{
  "ok": true,
  "service": "ui"
}
```

UI サーバの場合は `"service": "ui"`。

---

## リクエストパラメータ詳解

`/generate` と `/generate/stream` の `parameters` フィールドで以下をサポート：

### サーバ内部用パラメータ（モデルへは転送しない）

| キー | 型 | 説明 |
|------|-----|------|
| `think` | bool | モデルに推論（thinking）をさせるか（Ollama `--think` フラグに対応）|
| `reveal_thoughts` | bool | 内部思考を UI に表示するか |
| `save_inner` | bool | 内部思考をセッション履歴に保存するか |
| `inner_detail` | string | 思考の詳しさ（`"short"` or `"long"`） |
| `system_profile` | string | ローカルプロファイル名（例: `"default"`, `"detailed"`）— セキュアなファイル読み込み |
| `system_override` | string | 生のシステムプロンプト（ローカル開発・テスト用）— 外部アクセス時は非推奨 |

### その他（Ollama へ転送）

例： `options`, `num_predict` 等（Ollama の仕様に準じる）

---

## セキュリティに関する注意

1. **`system_override` の使用制限**:
   - ローカル開発環境でのみ使用を推奨します。
   - 任意のシステムプロンプト注入が可能なため、外部からのリクエスト送信を許可する環境では注意してください。
   - 本番運用では API に認証レイヤーを追加することを検討してください。

2. **CORS**:
   - API サーバは UI のオリジンに対して CORS を許可します（[src-py/main.py](main.py) 参照）。
   - スマートフォンなど別端末からアクセスする場合は、API ホスト／ポート設定に注意してください。

3. **セッション管理**:
   - コンテキスト（`context`）は LLM の入力パラメータにのみ使用され、外部へ送信されません。
   - `session_id` は任意の文字列で、認証されません。隔離した環境下での使用を想定しています。

---

## 環境変数設定例

### API サーバの起動

```bash
# デフォルトポート（8000）で起動
python -m uvicorn src-py.main:app --host 0.0.0.0 --port 8000

# あるいは設定ファイルから読み込む場合
python src-py/main.py
```

### UI サーバの起動

```bash
# 環境変数で API ホスト・ポートを指定
export API_HOST=192.168.0.10
export API_PORT=8000
export UI_PORT=8001

python -m uvicorn src-py.ui:app --host 0.0.0.0 --port 8001
```

---

## UI からの接続フロー

1. UI サーバ（`http://<LAN_IP>:8001`）でこのプロトコル実装（HTML/CSS/JS）を配信。
2. ブラウザが `/api-config` を呼び出して API ホスト・ポートを取得。
3. ブラウザからダイレクトに `/generate` または `/generate/stream` へ POST。
4. CORS ルールに従ってレスポンスを受け取る。

---

## 移行予定

- 本 UI サーバ（`src-py/ui.py`）は Python で主に静的配信を行っています。
- 将来的に `src-go` へ統合し、Go 側で同等の静的配信と `/system-profiles` ロジックを実装する予定。
- API 仕様（`/generate`, `/generate/stream` など）は安定版を目指しており、大きな変更は予定していません。
