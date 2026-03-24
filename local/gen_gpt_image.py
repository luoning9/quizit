#!/usr/bin/env python3
"""
使用 OpenAI GPT Image API 根据命令行参数生成图片。

示例：
  python local/gen_gpt_image.py "一个拿着红色滑板的机器人" out.jpg --size 1024x1024

依赖：
  pip install openai pillow

所需环境变量：
  OPENAI_API_KEY   或在仓库根目录 .env.local 中提供同名字段
"""

import argparse
import base64
import os
import sys
import traceback
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_MODEL = "gpt-image-1.5"
ENV_LOCAL_PATH = Path(__file__).resolve().parent / ".env.local"


def load_openai_api_key() -> str:
    """参考 gen_image.py 逻辑，支持环境变量与 .env.local。"""
    key = os.getenv("OPENAI_API_KEY")
    if not key and ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("OPENAI_API_KEY="):
                key = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        print("❌ 请设置 OPENAI_API_KEY 环境变量或在 .env.local 中提供。", file=sys.stderr)
        sys.exit(1)
    return key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用 GPT Image API 生成图片")
    parser.add_argument("prompt", help="图片描述提示词")
    parser.add_argument("out", type=Path, help="输出文件路径")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"模型名称，默认 {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--size",
        default="1024x1024",
        help='输出尺寸，如 "1024x1024"、"1024x1536"、"1536x1024"',
    )
    parser.add_argument(
        "--n",
        type=int,
        default=1,
        help="生成图片数量，默认 1（当前只保存第一张）",
    )
    parser.add_argument(
        "--format",
        default="jpeg",
        choices=["jpeg", "png", "webp"],
        help="输出格式，默认 jpeg",
    )
    parser.add_argument(
        "--quality",
        default="low",
        choices=["low", "hd"],
        help="输出质量，默认 low（低质量更便宜更快）",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)

    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)

    try:
        resp = client.images.generate(
            model=args.model,
            prompt=args.prompt,
            size=args.size,
            n=args.n,
            quality=args.quality,
        )

        if not resp.data:
            raise RuntimeError("响应中未包含图片数据")
        first = resp.data[0]
        image_bytes = None
        data_b64 = getattr(first, "b64_json", None)
        url = getattr(first, "url", None)

        if data_b64:
            image_bytes = base64.b64decode(data_b64)
        elif url:
            try:
                import requests

                resp_dl = requests.get(url, timeout=30)
                resp_dl.raise_for_status()
                image_bytes = resp_dl.content
                path = urlparse(url).path
                ext = Path(path).suffix.lower().lstrip(".")
                if ext in ("jpg", "jpeg", "png", "webp"):
                    args.format = "jpeg" if ext == "jpg" else ext
            except Exception as dl_err:
                raise RuntimeError(f"从 url 下载图片失败: {dl_err}") from dl_err

        if not image_bytes:
            raise RuntimeError("未找到可用的图片数据（无 b64_json 或 url）")
        mime = f"image/{args.format}"
    except Exception as e:
        traceback.print_exc()
        print(f"❌ 调用生成接口失败: {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(image_bytes)
    print(f"✅ 已保存到 {args.out} （{mime}）")


if __name__ == "__main__":
    main()
