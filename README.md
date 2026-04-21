docker run --runtime nvidia --gpus all `
-v "D:\research\Live-Vision-Narrator\models\hub\TrevorJS\gemma-4-E2B-it-uncensored:/app/model" `
-p 8000:8000 `
--ipc=host `
--rm `
vllm/vllm-openai:latest `
--model=/app/model `
--served-model-name=gemma-4-uncensored `
--dtype=bfloat16 `
--max-model-len=4096 `
--gpu-memory-utilization=0.8


<!-- # Ollama proxy (FastAPI)

> Low-latency resident FastAPI wrapper that forwards requests to a local Ollama instance.

## 要点
- Ollamaをローカルで常駐させ、`main.py`（FastAPI）に命令を投げます。
- 低遅延のためプロセス常駐 + `httpx.AsyncClient` の再利用を行っています。

## 使い方
1. Ollamaを起動（例: `ollama serve` 等）
2. このフォルダで仮想環境を作成して依存をインストール:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

3. サーバー起動（常駐で低遅延を重視するなら `--workers 1` 推奨）:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

4. 例: 生成リクエスト

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma-4-E4B-it-IQ4_XS", "prompt": "こんにちは"}'
```

### ストリーミング応答
低遅延用途ではストリーミングを使えます。バックエンドは `text/event-stream` でそのまま中継します。

```bash
curl -N -X POST http://127.0.0.1:8000/generate/stream \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma-4-E4B-it-IQ4_XS","prompt":"こんにちは"}'
```

## 環境変数
- `OLLAMA_URL` (default: `http://localhost:11434`)
- `OLLAMA_GENERATE_PATH` (default: `/api/generate`)
- `WARMUP_MODEL` (任意、起動時にプリロードしたいモデル名)

### NVIDIA GPU: 永続化モードの推奨

NVIDIA GPU を使用する場合、ドライバの電源管理により初回推論で遅延やデバイスのリセットが発生することがあります。サーバー常駐で安定して使うために永続化モードを有効化することを推奨します（管理者権限が必要）:

```bash
# 永続化モードを有効化
nvidia-smi -pm 1
```

注意: 管理者（または管理者権限のあるシェル）で実行してください。環境やドライバによっては再起動後に再実行が必要な場合があります。

# Live-Vision-Narrator

このプロジェクトの目的は、リアルタイムに人間と会話させるためのAIをローカルで動作させることです。

## ローカルモデルの追加（ollama）

ローカルでモデルを登録するには、ルートの `Modelfile` を使って次のコマンドを実行します:

```
ollama create live-narrator -f Modelfile
```

- `ollama`: Ollama CLI（ローカルでモデルを管理・実行するツール）。
- `create`: 新しいモデル定義を登録してビルドします（イメージ作成）。
- `live-narrator`: ローカルに登録するモデル名（任意の識別子）。
- `-f Modelfile`: モデル定義ファイルを指定します。リポジトリ内の `Modelfile` を使用します。

`Modelfile` の主な意味:
- `FROM ./gemma-4-E4B-it-IQ4_XS.gguf`: ベースとなる量子化済みGGUFファイルを指定します。
- `PARAMETER num_ctx`: コンテキスト長（履歴を扱うために大きめに設定）。
- `PARAMETER temperature`: 生成時の多様性（低めで安定、実況は0.7など）。
- `TEMPLATE "...": モデルに渡す対話フォーマットのテンプレート。

上記コマンドを実行すると、`live-narrator` という名前でローカルモデルが作成され、`ollama` を使って対話や推論ができるようになります。

必要に応じて `Modelfile` のパラメータや `FROM` のパスを編集してから実行してください。

### なぜ 8B クラスの Gemma 4 を選んだのか？

単にサイズが手頃だからではなく、Google の最先端 AI から知識を**蒸留（Distillation）**されたモデルであり、小さな VRAM 容量でも 70B クラスの巨大モデルに匹敵する論理的思考ができるからです。

### モデル情報の確認と実行

`ollama` で登録したモデルの情報確認や実行は次のコマンドを使います。

```
ollama show live-narrator
```

- `show`: 登録済みモデルのメタ情報やビルド設定、サイズ、利用可能なバージョンなどを表示します。モデルが正しく登録されたか、`FROM` の参照やパラメータが反映されているかを確認するのに使います。

```
ollama run live-narrator --think=false
```

- `run`: モデルを実行して対話セッションを開始したり、標準入力から入力を与えて推論を行います。対話的に使うときはそのまま実行して入力を打ち込みます。非対話で1回だけ推論する例:

```
echo "Hello" | ollama run live-narrator
```

- ollama run してから、`/set nothink` でThinkingを切るか、思考モードの制御は次のオプションで行います:
  - `--think=false`: Thinkingモードを無効にします。
  - `--think=true|high|medium|low`: Thinkingモードを有効化し、詳細度を指定します。
  - `--hidethinking`: Thinking出力を非表示にします。

- 詳細は `ollama --help` を参照してください。

---

## 心の声（inner voice）機能 — 概要

このプロジェクトでは、応答の「後付け推測（心の声）」をオプションで出力できる機能を実装しています。主に開発者向けのデバッグ／UX実験用で、UIトグルでON/OFF・保存・詳細度を切り替えできます。

主な特徴:
- メイン応答は常に短くシンプル（`Modelfile` の SYSTEM 指示に従う）。
- クライアントが `心の声を表示する` をONにした場合にのみ、別フィールドまたは `<inner_voice>...</inner_voice>` タグで後付けの推測を返す。
- `詳しく表示`（`short`/`long`）や `保存する`（セッション履歴へ保存）をUIで制御可能。
- ローカルの `Modelfile.detailed` を `System Profile` として選択すると、より詳しい出力ルールが適用される。

### UI とパラメータ（実装済み）
- トグル: `心の声を表示する` → リクエストに `parameters.reveal_thoughts=true` を付与。
- トグル: `心の声を保存する` → `parameters.save_inner=true` を付与（サーバが `SESSION_HISTORY` に保存）。
- セレクト: `詳しく表示` → `parameters.inner_detail = "short" | "long"`。
- セレクト: `System Profile` → `parameters.system_profile = "detailed"` で `Modelfile.detailed` を一時的に `system` として上書き。

### サーバ側の挙動（概略）
- `build_payload()` は `parameters.system_profile` を検査し、許可されたローカルファイル（`Modelfile` / `Modelfile.detailed`）を読み込んで `payload["system"]` に一時設定します（ログには中身を出力しません）。
- `reveal_thoughts` を要求するとモデルへ分かりやすく指示するためにプロンプト先頭に小さな制御タグ（例: `[REVEAL_INNER_VOICE]`）を付与します。
- 非ストリーミング/ストリーミング双方で、モデルが返す `thinking` フィールド、または `<inner_voice>...</inner_voice>` を検出して、`save_inner=true` の場合に `SESSION_HISTORY` に `role: assistant.inner` として保存します。

### Modelfile.detailed について
- このリポジトリに `Modelfile.detailed` を追加済みです。主な追加点:
  - `心の声` の出力ルール（structured/human モード）の指示と例を含む。
  - `structured` モードは `summary/evidence/alternatives/confidence` を短く列挙する形式（JSONまたは `<inner_voice>{...}</inner_voice>`）。
  - `human` モードは感情的・人間的表現の短文＋根拠1文を出す形式。

### 制御タグ（プロンプト先頭）
- `[REVEAL_INNER_VOICE]` — 心の声を出す許可。
- `[INNER_STYLE:structured]` / `[INNER_STYLE:human]` — 出力のスタイルを指定。

サンプル（non-stream）リクエスト例:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "live-narrator",
    "prompt": "あの動きどう思う？",
    "parameters": {
      "reveal_thoughts": true,
      "save_inner": true,
      "inner_detail": "long",
      "system_profile": "detailed"
    },
    "session_id": "default"
  }'
```

レスポンスは通常の `response` に加えて、`thinking` または `<inner_voice>...</inner_voice>` を含むことがあります（UIでは `心の声` セクションとして表示）。

### 安全・運用メモ
- 逐語的チェイン・オブ・ソート（モデル内部のトークン列）を出力しないよう設計しています。心の声は要約や短い人間的表現に限定してください。
- `system_profile` で読み込むファイルの中身はサーバログに出力しないでください（現実装ではログに記録しません）。
- この機能は開発用のUX実験向けです。永続的運用時は保存ポリシーやアクセス制御を検討してください。

### 動作確認手順（簡潔）
1. サーバ起動:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

2. ブラウザで `http://127.0.0.1:8000/ui` を開き、
   - `心の声を表示する` を ON にする
   - `詳しく表示` を `詳しい` にする（必要なら `保存する` を ON）
   - `System Profile` を `detailed` に切り替える
   - プロンプトを送信して応答と心の声を確認する

3. セッション履歴の確認:

```bash
curl -X POST http://127.0.0.1:8000/session/get -H "Content-Type: application/json" -d '{"session_id":"default"}'
```

保存された `assistant.inner` が `history` に含まれるはずです（`save_inner` を有効にした場合）。

---

必要なら、`parameters.inner_style`（`human`/`structured`）を受けて自動的に制御タグを付与するサーバ側パッチも作ります。要望があれば続けます。 -->
