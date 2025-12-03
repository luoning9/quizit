#!/usr/bin/env python3
"""
使用 Google Imagen 接口根据提示词生成一张图片。

示例：
  python local/generate_image.py "a cozy reading room with green plants" --out reading.png

依赖：
  pip install google-generativeai

所需环境变量：
  GOOGLE_API_KEY   或在仓库根目录 .env.local 中提供同名字段
"""

import argparse
import base64
import os
import sys
from pathlib import Path
from typing import Optional

ENV_LOCAL_PATH = Path(__file__).resolve().parent.parent / ".env.local"


def load_google_api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY")
    if not key and ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            if line.strip().startswith("GOOGLE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        print("❌ 请设置 GOOGLE_API_KEY 环境变量或在 .env.local 中提供。", file=sys.stderr)
        sys.exit(1)
    return key


def save_image_from_b64(data_b64: str, out_path: Path) -> None:
    raw = base64.b64decode(data_b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def generate_image(prompt: str, model_name: str, out_path: Path, mime_type: Optional[str]) -> None:
    try:
        import google.generativeai as genai
    except ImportError:
        print("❌ 未找到 google-generativeai，请先安装：pip install google-generativeai", file=sys.stderr)
        sys.exit(1)

    api_key = load_google_api_key()
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(model_name=model_name)
    print(f"👉 使用模型 {model_name} 生成图片...")
    try:
        resp = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            mime_type=mime_type or None,
        )
    except Exception as e:
        print(f"❌ 调用生成接口失败: {e}", file=sys.stderr)
        sys.exit(1)

    images = getattr(resp, "images", None)
    if not images:
        print("❌ 未获得图片数据。完整响应：", resp, file=sys.stderr)
        sys.exit(1)

    img = images[0]
    data_b64 = getattr(img, "data", None) or getattr(img, "image", None)
    if not data_b64:
        print("❌ 无法从响应中提取图片数据。完整响应：", resp, file=sys.stderr)
        sys.exit(1)

    save_image_from_b64(data_b64, out_path)
    print(f"✅ 已保存到 {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用 Google Imagen 生成一张图片")
    parser.add_argument("prompt", help="图片描述")
    parser.add_argument(
        "--model",
        default="imagen-3.0-generate-001",
        help="模型名称，默认 imagen-3.0-generate-001",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output.png"),
        help="输出文件路径，默认 output.png",
    )
    parser.add_argument(
        "--mime",
        default=None,
        help="可选：指定 mime type，如 image/png 或 image/jpeg；默认由服务端决定",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    generate_image(args.prompt, args.model, args.out, args.mime)


if __name__ == "__main__":
    main()
