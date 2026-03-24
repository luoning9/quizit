#!/usr/bin/env python3
"""
使用 Google Imagen 4 接口根据命令行参数生成图片。

示例：
  python local/gen_imagen4.py "a cozy reading nook" out.jpg

依赖：
  pip install google-genai

所需环境变量：
  GOOGLE_API_KEY   或在仓库根目录 .env.local 中提供同名字段
"""

import argparse
import base64
import os
import sys
import traceback
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from google import genai
from google.genai import types

DEFAULT_MODEL = "imagen-4.0-generate-001"
ENV_LOCAL_PATH = Path(__file__).resolve().parent / ".env.local"


def load_google_api_key() -> str:
    """参考 gen_image.py 中的实现，支持环境变量与本地 .env.local。"""
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOLE_API_KEY")
    if not key and ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("GOOGLE_API_KEY=") or stripped.startswith("GOOLE_API_KEY="):
                key = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        print("❌ 请设置 GOOGLE_API_KEY 环境变量或在 .env.local 中提供。", file=sys.stderr)
        sys.exit(1)
    return key


def extract_first_image(resp) -> Tuple[bytes, str]:
    """
    从 generate_images 响应中提取首个图片字节流与 MIME。
    仅使用 response.generated_images。
    """
    generated = getattr(resp, "generated_images", None)
    if not generated:
        # 打印调试信息便于排查返回结构
        print(f"⚠️ 未获取到 generated_images，响应类型={type(resp)}，内容={resp}", file=sys.stderr)
        raise RuntimeError("未从响应中提取到图片数据。")
    if not isinstance(generated, (list, tuple)):
        generated = [generated]

    for item in generated:
        img_obj = getattr(item, "image", None)
        mime = "image/png"
        if img_obj is not None:
            mime = getattr(img_obj, "mime_type", None) or mime
            data = getattr(img_obj, "image_bytes", None)
            if isinstance(data, bytes):
                return data, mime
            if isinstance(data, str):
                try:
                    return base64.b64decode(data), mime
                except Exception:
                    pass

            pil_image = getattr(img_obj, "_loaded_image", None)
            if pil_image is not None:
                buf = BytesIO()
                fmt = pil_image.format or "PNG"
                pil_image.save(buf, format=fmt)
                return buf.getvalue(), f"image/{fmt.lower()}"

        # 兜底：某些情况下 GeneratedImage 可能直接有 bytes/data
        data = getattr(item, "image_bytes", None) or getattr(item, "bytes", None) or getattr(item, "data", None)
        if isinstance(data, bytes):
            return data, mime
        if isinstance(data, str):
            try:
                return base64.b64decode(data), mime
            except Exception:
                pass

        inline = getattr(item, "inline_data", None)
        if inline and getattr(inline, "data", None):
            inline_mime = getattr(inline, "mime_type", None) or mime
            return bytes(inline.data), str(inline_mime)

    raise RuntimeError("未从响应中提取到图片数据。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用 Google Imagen 4 生成图片")
    parser.add_argument("prompt", help="图片描述提示词")
    parser.add_argument("out", type=Path, help="输出文件路径")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"模型名称，默认 {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="1:1",
        help='长宽比，格式如 "1:1"、"4:3"、"9:16"',
    )

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)

    api_key = load_google_api_key()
    client = genai.Client(api_key=api_key)

    try:
        # 根据官方示例使用 generate_images 与 GenerateImagesConfig。
        resp = client.models.generate_images(
            model=args.model,
            prompt=args.prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=args.aspect_ratio,
            ),
        )
        image_bytes, mime = extract_first_image(resp)
    except Exception as e:
        traceback.print_exc()
        print(f"❌ 调用生成接口失败: {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(image_bytes)
    print(f"✅ 已保存到 {args.out} （{mime}）")


if __name__ == "__main__":
    main()
