"""マージ済みモデルを 4bit で読み込み、ローカル対話を行う CLI。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow 未導入でもテキスト対話は可能
    Image = None


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
DEFAULT_MODEL_DIR = WORKSPACE_ROOT / "models" / "heretic_merged" / "gemma-4-E4b-it"
DEFAULT_PROCESSOR_DIR = WORKSPACE_ROOT / "models" / "hub" / "google" / "gemma-4-E4B-it"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="4bit 量子化モデルと対話します。")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="マージ済みモデルのディレクトリ",
    )
    parser.add_argument(
        "--processor-dir",
        type=Path,
        default=DEFAULT_PROCESSOR_DIR,
        help="processor_config.json を含むディレクトリ",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=128,
        help="1 回の応答で生成する最大トークン数",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="サンプリング温度",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=0.9,
        help="nucleus sampling の top-p",
    )
    parser.add_argument(
        "--trust-remote-code",
        action="store_true",
        help="モデルロード時に trust_remote_code=True を指定",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="KV キャッシュを有効化（VRAM 使用量が増える可能性あり）",
    )
    return parser.parse_args()


def ensure_bitsandbytes_cuda_backend() -> None:
    try:
        from bitsandbytes import cextension as bnb_cextension
    except Exception as error:
        raise RuntimeError(
            "bitsandbytes の読み込みに失敗しました。CUDA 版 bitsandbytes をインストールしてください。"
        ) from error

    native_lib = getattr(bnb_cextension, "lib", None)
    compiled_with_cuda = bool(getattr(native_lib, "compiled_with_cuda", False))
    if not compiled_with_cuda:
        raise RuntimeError(
            "bitsandbytes が CPU バックエンドで動作しています。CUDA 版 bitsandbytes へ切り替えてください。"
        )


def load_model_and_processor(
    model_dir: Path, processor_dir: Path, trust_remote_code: bool
) -> tuple[Any, Any]:
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA が利用できません。4bit 量子化モデルを VRAM に載せたい場合は、CUDA 対応の PyTorch / bitsandbytes 環境が必要です。"
        )

    ensure_bitsandbytes_cuda_backend()

    print(f"CUDA デバイス: {torch.cuda.get_device_name(0)}")

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )

    print("モデルを読み込み中（GPU 強制 / 4bit）...")
    model = AutoModelForImageTextToText.from_pretrained(
        str(model_dir),
        device_map={"": 0},
        dtype=torch.float16,
        quantization_config=quantization_config,
        trust_remote_code=trust_remote_code,
    )
    processor = AutoProcessor.from_pretrained(
        str(processor_dir), trust_remote_code=trust_remote_code
    )

    print("ロード形式: AutoModelForImageTextToText")
    return model, processor


def build_text_prompt(processor: Any, messages: list[dict[str, str]]) -> str:
    if hasattr(processor, "apply_chat_template"):
        return processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    lines: list[str] = []
    for message in messages:
        role = message["role"]
        text = message["content"]
        lines.append(f"{role}: {text}")
    lines.append("assistant:")
    return "\n".join(lines)


def generate_reply(
    model: Any,
    processor: Any,
    messages: list[dict[str, str]],
    image_path: Path | None,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    use_cache: bool,
) -> str:
    if image_path is not None and Image is None:
        raise RuntimeError("画像入力には Pillow が必要です。`pip install pillow` を実行してください。")

    image = None
    if image_path is not None:
        if not image_path.exists():
            raise FileNotFoundError(f"画像が見つかりません: {image_path}")
        image = Image.open(image_path).convert("RGB")

    prompt = build_text_prompt(processor, messages)

    processor_kwargs: dict[str, Any] = {
        "text": prompt,
        "return_tensors": "pt",
    }
    if image is not None:
        processor_kwargs["images"] = [image]

    inputs = processor(**processor_kwargs)

    input_device = next(model.parameters()).device
    inputs = {
        k: (v.to(input_device) if hasattr(v, "to") else v) for k, v in inputs.items()
    }

    output_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=True,
        temperature=temperature,
        top_p=top_p,
        use_cache=use_cache,
    )

    generated_ids = output_ids[0][inputs["input_ids"].shape[-1] :]
    tokenizer = getattr(processor, "tokenizer", processor)
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def main() -> int:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    if not model_dir.is_dir():
        raise FileNotFoundError(f"モデルディレクトリが見つかりません: {model_dir}")

    print("=== ローカル対話モード ===")
    print(f"モデル: {model_dir}")
    print(f"processor: {args.processor_dir.resolve()}")
    print("終了: /exit")
    print("履歴クリア: /clear")
    print("画像指定（Vision のみ）: /img <画像パス>")
    print()

    model, processor = load_model_and_processor(
        model_dir,
        args.processor_dir.resolve(),
        trust_remote_code=args.trust_remote_code,
    )

    messages: list[dict[str, str]] = []
    image_path: Path | None = None

    while True:
        user_text = input("あなた > ").strip()

        if not user_text:
            continue
        if user_text == "/exit":
            print("終了します。")
            break
        if user_text == "/clear":
            messages.clear()
            print("履歴をクリアしました。")
            continue
        if user_text.startswith("/img "):
            image_path = Path(user_text[5:].strip()).expanduser()
            print(f"画像を設定しました: {image_path}")
            continue

        messages.append({"role": "user", "content": user_text})

        try:
            reply = generate_reply(
                model=model,
                processor=processor,
                messages=messages,
                image_path=image_path,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                use_cache=args.use_cache,
            )
        except Exception as error:
            messages.pop()
            print(f"生成中にエラーが発生しました: {error}")
            continue

        print(f"モデル > {reply}")
        messages.append({"role": "assistant", "content": reply})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
