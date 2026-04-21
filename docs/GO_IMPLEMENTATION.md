# Go 実装 — PoC for Live-Vision-Narrator

Pure Go のマイグレーション PoC。python FastAPI 実装をベースに低レイテンシなオーケストレータを実装します。

## アーキテクチャ

```
UI (JavaScript)
    ↓ /generate または /generate/stream
    ↓
Go Server (main.go)
    ├─ Endpoint: /generate (非ストリーミング)
    ├─ Endpoint: /generate/stream (ストリーミング NDJSON)
    ├─ Endpoint: /models
    ├─ Endpoint: /session/reset
    └─ Endpoint: /session/get

    ↓
api.OllamaClient
    └─ HTTP クライアント + bufio.Reader (低レイテンシ行読み)

    ↓
processor.TextProcessor
    └─ 正規表現（事前コンパイル済み）による text sanitization

    ↓
api.AivisClient (非同期バックグラウンド)
    └─ 音声合成API への投げっぱなし
```

## ビルド

```bash
# 初回: 依存関係をダウンロード
go mod download

# ビルド
make build

# または直接
go build -o narrator_engine .
```

## 実行

```bash
# ローカル開発（ホット リロードは air 必要）
make run

# または直接
./narrator_engine

# クロスコンパイル (Linux)
make cross-build-linux

# クロスコンパイル (Windows)
make cross-build-windows
```

## 設定

`config.toml` または環境変数で設定可能：

```toml
ollama_url = "http://localhost:11434"
ollama_generate_path = "/api/generate"
ollama_models_path = "/api/tags"
default_think = false
default_model = "live-narrator"
log_level = "INFO"

host_ip = "0.0.0.0"
ui_ip = "0.0.0.0"
api_host = "localhost"
api_port = 8000
ui_port = 8001

system_default_file = "Modelfile"
system_detailed_file = "Modelfile.detailed"

model_idle_seconds = 2000
```

## API ドキュメント

Python FastAPI 版と互換。

### POST /generate
非ストリーミング生成。

**Request:**
```json
{
  "model": "live-narrator",
  "prompt": "やあ、今何してる？",
  "parameters": {
    "think": false,
    "reveal_thoughts": false,
    "save_inner": false
  },
  "session_id": "default"
}
```

**Response:**
```json
{
  "response": "...",
  "tokens": {
    "prompt_tokens": 10,
    "completion_tokens": 50,
    "total_tokens": 60
  },
  "elapsed_ms": 123.45,
  "context": [...]
}
```

### POST /generate/stream
ストリーミング生成。NDJSON 形式で行単位でレスポンスを返す。

**Request:** `/generate` と同じ。

**Response (NDJSON):**
```
{"elapsed_ms": 350.0}
{"response": "やあ", "done": false}
{"response": "、", "done": false}
{"response": "元気", "done": false}
...
{"response": "？", "done": true, "context": [...]}
```

### POST /session/reset
セッションコンテキストを初期化。

**Request:**
```json
{
  "session_id": "default"
}
```

**Response:**
```json
{
  "ok": true,
  "session_id": "default"
}
```

### POST /session/get
セッション履歴とコンテキストを取得。

**Request:**
```json
{
  "session_id": "default"
}
```

**Response:**
```json
{
  "ok": true,
  "session_id": "default",
  "has_context": true,
  "context_length": 512,
  "history_length": 5,
  "history": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "..."}
  ],
  "context": [...]
}
```

## パフォーマンス計測

すべてのエンドポイントは内部プロファイルを行い、以下をログ出力します：

```
PROFILE /generate A_recv=350.50ms B_recv_to_preToken=2.30ms total=360.80ms
PROFILE /generate/stream A_recv=355.20ms B_recv_to_preToken=3.10ms total=820.00ms first_chunk=365.40ms
```

- **A_recv_ms**: Ollama リクエストを送信してからレスポンスを受け取るまで（ネットワークRTT）
- **B_recv_to_preToken_ms**: レスポンス受信直後からテキスト処理完了までの時間（アプリ側処理）
- **total_ms**: エンドツーエンド総処理時間
- **first_chunk_ms** (ストリーム): 最初のチャンク受信までの時間

目標値：
- A_recv_ms < 450ms（Ollama の推論時間）
- B_recv_to_preToken_ms < 5ms（アプリ側処理は軽く）
- 総レイテンシ < 500ms

## ファイル構成

```
live-narrator/
├── main.go                 # エントリーポイント、HTTP ハンドラ
├── go.mod, go.sum         # 依存関係
├── config/
│   └── config.go          # 設定の読み込み
├── api/
│   ├── ollama_client.go    # Ollama HTTP クライアント（ストリーム対応）
│   └── aivis_client.go     # Aivis 非同期クライアント（スタブ）
├── processor/
│   └── text_processor.go   # テキスト整形・sanitize
├── util/
│   └── profiling.go        # プロファイル計測ユーティリティ
├── Makefile                # ビルド設定
└── README.md               # このファイル
```

## 次のステップ

1. **ローカルテスト**: ローカル Ollama で `/generate` と `/generate/stream` をテスト。
2. **ベースライン計測**: Python 版と Go 版の A/B 計測を比較（目標: B < 5ms）。
3. **Hotspot 検出**: プロファイルで遅い箇所を特定。
4. **ネイティブ最適化**: 必要なら遅い処理を別プロセスやネイティブコードに切り出す。

## トラブルシューティング

- **"connection refused"**: Ollama サーバーが起動していない。`ollama serve` を実行。
- **ストリームがハング**: Ollama のレスポンス待ち。ネットワーク遅延を確認。
- **テキストが文字化け**: JSON エンコーディング。UTF-8 を確認。
