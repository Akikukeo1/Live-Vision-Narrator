# Ollama proxy (FastAPI)

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

## 環境変数
- `OLLAMA_URL` (default: `http://localhost:11434`)
- `OLLAMA_GENERATE_PATH` (default: `/api/generate`)
- `WARMUP_MODEL` (任意、起動時にプリロードしたいモデル名)# Live-Vision-Narrator

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
