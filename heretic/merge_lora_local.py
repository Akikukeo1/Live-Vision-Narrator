#!/usr/bin/env python3
"""ローカル環境で LoRA アダプタをベースモデルへマージするスクリプト。"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent

DEFAULT_BASE_MODEL_DIR = WORKSPACE_ROOT / "models" / "hub" / "google" / "gemma-4-E4B-it"
DEFAULT_ADAPTER_DIR = WORKSPACE_ROOT / "models" / "heretic_adapters" / "gemma-4-E4b-it"
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "models" / "heretic_merged" / "gemma-4-E4b-it"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "LoRA アダプタをベースモデルへ統合し、マージ済みモデルを保存します。"
        )
    )
    parser.add_argument(
        "--base-model-dir",
        type=Path,
        default=DEFAULT_BASE_MODEL_DIR,
        help="ベースモデルのディレクトリ",
    )
    parser.add_argument(
        "--adapter-dir",
        type=Path,
        default=DEFAULT_ADAPTER_DIR,
        help="adapter_config.json と adapter_model.safetensors があるディレクトリ",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="マージ済みモデルの出力先ディレクトリ",
    )
    parser.add_argument(
        "--dtype",
        choices=["bfloat16", "float16", "float32"],
        default="bfloat16",
        help="モデル読み込み時の dtype",
    )
    parser.add_argument(
        "--device-map",
        default="cpu",
        help="transformers の device_map（例: cpu, auto）",
    )
    parser.add_argument(
        "--trust-remote-code",
        action="store_true",
        help="モデルロード時に trust_remote_code=True を指定する",
    )
    parser.add_argument(
        "--max-shard-size",
        default="5GB",
        help="save_pretrained の max_shard_size（例: 2GB, 5GB）",
    )
    return parser.parse_args()


def resolve_dtype(dtype_name: str) -> torch.dtype:
    if dtype_name == "bfloat16":
        return torch.bfloat16
    if dtype_name == "float16":
        return torch.float16
    return torch.float32


def validate_paths(base_model_dir: Path, adapter_dir: Path) -> None:
    if not base_model_dir.is_dir():
        raise FileNotFoundError(
            f"ベースモデルのディレクトリが見つかりません: {base_model_dir}"
        )

    if not adapter_dir.is_dir():
        raise FileNotFoundError(
            f"アダプタのディレクトリが見つかりません: {adapter_dir}"
        )

    adapter_config = adapter_dir / "adapter_config.json"
    adapter_safetensors = adapter_dir / "adapter_model.safetensors"
    adapter_bin = adapter_dir / "adapter_model.bin"

    if not adapter_config.exists():
        raise FileNotFoundError(
            f"adapter_config.json が見つかりません: {adapter_config}"
        )

    if not adapter_safetensors.exists() and not adapter_bin.exists():
        raise FileNotFoundError(
            "adapter_model.safetensors または adapter_model.bin が見つかりません"
        )


def print_recommended_layout() -> None:
    print("=== 推奨ディレクトリ構成（ローカル） ===")
    print(f"ベースモデル  : {DEFAULT_BASE_MODEL_DIR}")
    print(f"LoRAアダプタ  : {DEFAULT_ADAPTER_DIR}")
    print(f"出力（マージ）: {DEFAULT_OUTPUT_DIR}")
    print()


def main() -> int:
    args = parse_args()
    print_recommended_layout()

    base_model_dir = args.base_model_dir.resolve()
    adapter_dir = args.adapter_dir.resolve()
    output_dir = args.output_dir.resolve()

    validate_paths(base_model_dir, adapter_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dtype = resolve_dtype(args.dtype)

    print("=== マージ開始 ===")
    print(f"ベースモデル: {base_model_dir}")
    print(f"アダプタ    : {adapter_dir}")
    print(f"出力先      : {output_dir}")
    print(f"dtype       : {args.dtype}")
    print(f"device_map  : {args.device_map}")
    print()

    print("1/4 ベースモデルとトークナイザを読み込み中...")
    tokenizer = AutoTokenizer.from_pretrained(
        str(base_model_dir),
        trust_remote_code=args.trust_remote_code,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        str(base_model_dir),
        torch_dtype=dtype,
        device_map=args.device_map,
        trust_remote_code=args.trust_remote_code,
    )

    print("2/4 LoRA アダプタを適用中...")
    peft_model = PeftModel.from_pretrained(
        base_model,
        str(adapter_dir),
        is_trainable=False,
    )

    print("3/4 マージ中...")
    merged_model = peft_model.merge_and_unload()

    print("4/4 保存中...")
    merged_model.save_pretrained(
        str(output_dir),
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )
    tokenizer.save_pretrained(str(output_dir))

    print()
    print("マージが完了しました。")
    print(f"出力先: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
