# src-py/abliterator/download_model.py
from huggingface_hub import snapshot_download
import os

model_id = "Qwen/Qwen2.5-7B-Instruct" # 例としてQwen2.5。3.5ならそのID
save_path = "../../models/hub/Qwen2.5-7B-Instruct"

os.makedirs(save_path, exist_ok=True)

print(f"Downloading {model_id} to {save_path}...")
snapshot_download(
    repo_id=model_id,
    local_dir=save_path,
    local_dir_use_symlinks=False, # Windows環境ではFalseが無難
    ignore_patterns=["*.msgpack", "*.h5", "*.ot"] # 不要な形式を除外して節約
)
print("Done!")
