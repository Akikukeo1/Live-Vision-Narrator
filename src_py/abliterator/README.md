# abliterator

./Hereticを使用する方向へ変更。

Abliteratorは、特定のLLMモデルから「拒否（reject）に関するベクトル」を検出・削除し、モデルの応答や embeddings の振る舞いを調整するためのユーティリティです。

ディスクに100GB以上の空きを用意していないと、正常に動作しない可能性があります。特に、モデルの拒否ベクトルを抽出する際に大量のデータが生成されるためです。

**目的**
- 不適切、誤情報、または望ましくない応答を引き起こす可能性がある埋め込み（ベクトル）やトークンに対して行われる過度なフィルタリングを改善する。

## 実行方法

### 環境をセットアップ

uv sync 実行後、更新するため
uv pip install -U peft transformers accelerate
uv pip install git+https://github.com/huggingface/transformers.git
uv pip install git+https://github.com/huggingface/peft.git
で、手動インストールしてください。

### ライブラリの書き換え

src_py\abliterator\.venv\Lib\site-packages\heretic\model.py
345 行目付近 get_layer_modules 関数

```python
try_add("attn.o_proj", layer.self_attn.o_proj)  # ty:ignore[possibly-missing-attribute]
```
```python
# =================改造=================
# Qwen3.5 (GatedDeltaNet) や Llama系など、多様なアーキテクチャに対応
if hasattr(layer, 'linear_attn'):
    # linear_attn 内のプロジェクション層を探索
    if hasattr(layer.linear_attn, 'out_proj'):
        try_add("attn.o_proj", layer.linear_attn.out_proj)
    elif hasattr(layer.linear_attn, 'o_proj'):
        try_add("attn.o_proj", layer.linear_attn.o_proj)
    else:
        print("DEBUG: No output projection found in linear_attn.")

elif hasattr(layer, 'self_attn'):
    # 標準的な Llama / Qwen (旧) などの構造
    if hasattr(layer.self_attn, 'o_proj'):
        try_add("attn.o_proj", layer.self_attn.o_proj)
    elif hasattr(layer.self_attn, 'out_proj'):
        try_add("attn.o_proj", layer.self_attn.out_proj)

else:
    print("DEBUG: No attention module recognized in this layer.")
# =================改造=================
```

470行目付近

```python
base_weight = cast(Tensor, module.base_layer.weight)
```
```python
# =================改造=================
if hasattr(module, "base_layer"):
    base_weight = cast(Tensor, module.base_layer.weight)
else:
    # LoRAでラップされていない（通常のLinear層）場合は直接weightを参照する
    base_weight = cast(Tensor, module.weight)
# =================改造=================
```

541

weight_A = cast(Tensor, module.lora_A["default"].weight)
weight_B = cast(Tensor, module.lora_B["default"].weight)
weight_A.data = lora_A.to(weight_A.dtype)
weight_B.data = lora_B.to(weight_B.dtype)

# =================改造=================
print(f"DEBUG: module type: {type(module)}")
print(f"DEBUG: module attributes: {dir(module)}")
# =================改造=================
weight_A = cast(Tensor, module.lora_A["default"].weight)
weight_B = cast(Tensor, module.lora_B["default"].weight)
weight_A.data = lora_A.to(weight_A.dtype)
weight_B.data = lora_B.to(weight_B.dtype)


### 実行

```powershell
uv run --no-sync heretic `
--model D:/research/Live-Vision-Narrator/models/hub/Qwen3.5-9B `
--device-map auto `
--quantization BNB_4BIT

# または、量子化なしで実行する場合は以下のようにします。（推奨）

uv run --no-sync heretic `
--model D:/research/Live-Vision-Narrator/models/hub/Qwen3.5-9B `
--device-map "balanced" `
--max-memory '{"0": "6GiB", "cpu": "24GiB"}'
```

## ライセンス
プロジェクト全体のライセンスに従います。
