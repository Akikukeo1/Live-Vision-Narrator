# abliterator

Abliteratorは、特定のLLMモデルから「拒否（reject）に関するベクトル」を検出・削除し、モデルの応答や embeddings の振る舞いを調整するためのユーティリティです。

ディスクに100GB以上の空きを用意していないと、正常に動作しない可能性があります。特に、モデルの拒否ベクトルを抽出する際に大量のデータが生成されるためです。

**目的**
- 不適切、誤情報、または望ましくない応答を引き起こす可能性がある埋め込み（ベクトル）やトークンに対して行われる過度なフィルタリングを改善する。

## 実行方法

### 環境をセットアップ

uv sync 実行後、Transformerを更新するため
uv pip install git+https://github.com/huggingface/transformers.git
で、手動インストールしてください。

src_py\abliterator\.venv\Lib\site-packages\heretic\model.py
345 行目付近を探す:
get_layer_modules という関数の中に以下の行があるはずです。

### ライブラリの書き換え

```python
try_add("attn.o_proj", layer.self_attn.o_proj)  # ty:ignore[possibly-missing-attribute]
```
以下のように書き換えて保存:

```python
print(f"DEBUG: linear_attn attributes: {dir(layer.linear_attn)}")
# Qwen3.5 (GatedDeltaNet) 対応のため out_proj を参照するように変更
try:
    try_add("attn.o_proj", layer.linear_attn.out_proj)
except AttributeError:
    try_add("attn.o_proj", layer.linear_attn.o_proj)
```

### 実行

```powershell
uv run --no-sync heretic `
--model D:/research/Live-Vision-Narrator/models/hub/Qwen3.5-9B `
--device-map auto `
--quantization BNB_4BIT

# または、量子化なしで実行する場合は以下のようにします。（推奨）

uv run --no-sync heretic `
--model D:/research/Live-Vision-Narrator/models/hub/Qwen3.5-9B `
--device-map auto `
--max-memory '{"0": "7GiB", "cpu": "32GiB"}'
```

## ライセンス
プロジェクト全体のライセンスに従います。
