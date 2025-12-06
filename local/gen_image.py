#!/usr/bin/env python3
"""
使用 Google GenAI 的 Imagen 接口根据提示词生成一张图片。

示例：
  python local/generate_image.py "a cozy reading room with green plants" --out reading.png

依赖：
  pip install google-genai

所需环境变量：
  GOOGLE_API_KEY   或在仓库根目录 .env.local 中提供同名字段
"""

import argparse
import base64
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image  # pillow 必须安装，否则直接抛异常

DEFAULT_MODEL = "gemini-2.5-flash-image"

ENV_LOCAL_PATH = Path(__file__).resolve().parent.parent / ".env.local"


def load_google_api_key() -> str:
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


def save_image_from_b64(data_b64: str, out_path: Path) -> None:
    raw = base64.b64decode(data_b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def compress_to_jpeg(raw: bytes, target_kb: int = 50, max_dim: int = 1600) -> tuple[bytes, str]:
    """
    将图片转成 JPEG，并尝试压到目标体积附近；即便不需压缩也统一输出 JPG。
    返回 (bytes, mime)。
    """
    with BytesIO(raw) as bio:
        with Image.open(bio) as img:
            img = img.convert("RGB")
            w, h = img.size
            scale = min(1.0, max_dim / max(w, h))
            min_dim = 320  # 避免缩得过小导致严重失真
            best_bytes: Optional[bytes] = None
            best_size_kb: Optional[float] = None

            def jpeg_bytes(im, quality: int) -> bytes:
                buf = BytesIO()
                im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
                return buf.getvalue()

            while True:
                work = img
                if scale < 1.0:
                    work = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

                lo, hi = 10, 95
                local_best = None
                local_size = None
                while lo <= hi:
                    q = (lo + hi) // 2
                    data = jpeg_bytes(work, q)
                    size_kb = len(data) / 1024
                    if size_kb <= target_kb:
                        local_best = data
                        local_size = size_kb
                        hi = q - 1
                    else:
                        lo = q + 1

                if local_best:
                    best_bytes, best_size_kb = local_best, local_size
                    break

                # 如果压到最低质量仍大于目标，则继续缩尺寸
                scale *= 0.85
                if max(work.size) <= min_dim or scale <= 0.2:
                    # 兜底使用最低质量结果
                    fallback = jpeg_bytes(work, 10)
                    best_bytes, best_size_kb = fallback, len(fallback) / 1024
                    break

            if best_bytes and best_size_kb is not None:
                if best_size_kb > target_kb:
                    print(f"⚠️ 仅压到约 {best_size_kb:.1f}KB（目标 {target_kb}KB），已尽量保持清晰。", file=sys.stderr)
                return best_bytes, "image/jpeg"
    return raw, "image/jpeg"


def build_prompt(prompt: str) -> str:
    return (
        "请生成一张适用于历史试卷的黑白图片。构图简洁，信息点突出，缩小后仍清晰。"
        "人物服饰和场景必须符合当时历史背景，避免现代物品。背景尽量简化或虚化，不要装饰性元素。"
        "整体风格严肃、清晰、易于学生识别历史情境。图片内容如下："
        f"{prompt}"
    )


def generate_image_bytes(
    prompt: str,
    target_kb: int = 50,
    model_name: str = DEFAULT_MODEL,
    aspect_ratio: str = "4:3",
) -> tuple[bytes, str]:
    """根据提示词生成图片并压缩到目标体积，返回 (字节流, mime_type)。"""
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError("未找到 google-genai，请先安装：pip install google-genai") from e

    api_key = load_google_api_key()
    client = genai.Client(api_key=api_key)
    prompt_bw = build_prompt(prompt)

    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt_bw,
            config=genai.types.GenerateContentConfig(
                response_modalities=["image"],
                image_config=genai.types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                ),
            ),
        )
    except Exception as e:
        raise RuntimeError(f"调用生成接口失败: {e}") from e

    raw_bytes: Optional[bytes] = None
    mime_type: str = "image/png"
    parts: list = []
    if hasattr(resp, "candidates") and resp.candidates:
        for cand in resp.candidates:
            content = getattr(cand, "content", None)
            if content and getattr(content, "parts", None):
                parts.extend(content.parts)
            finish = getattr(cand, "finish_reason", None)
            if finish and finish not in ("STOP", "MAX_TOKENS"):
                print(f"⚠️ 候选被终止，finish_reason={finish}", file=sys.stderr)
    if not parts and hasattr(resp, "parts") and getattr(resp, "parts") is not None:
        parts = list(getattr(resp, "parts"))

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            raw_bytes = inline.data
            if getattr(inline, "mime_type", None):
                mime_type = str(inline.mime_type)
            break
        data_field = getattr(part, "data", None)
        if isinstance(data_field, bytes):
            raw_bytes = data_field
            break
        if isinstance(data_field, str):
            try:
                raw_bytes = base64.b64decode(data_field)
                break
            except Exception:
                pass

    if not raw_bytes:
        raise RuntimeError("无法从响应中提取图片数据（可能被安全过滤或响应为空）。")

    compressed, mime_type = compress_to_jpeg(raw_bytes, target_kb=target_kb)
    return compressed, mime_type


def generate_image(prompt: str, model_name: str, out_path: Path, mime_type: Optional[str]) -> None:
    try:
        raw_bytes = generate_image_bytes(prompt, target_kb=50, model_name=model_name)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw_bytes)
    print(f"✅ 已保存到 {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用 Google GenAI Imagen 生成一张图片")
    parser.add_argument("prompt", help="图片描述")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="模型名称，默认 gemini-2.5-flash-image",
    )
    parser.add_argument(
        "--target-kb",
        type=int,
        default=50,
        help="目标文件大小（KB），默认 50",
    )
    parser.add_argument(
        "out",
        type=Path,
        help="输出文件路径",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)

    # 复用 CLI 输出，调用接口函数生成图片
    try:
        raw, mime = generate_image_bytes(args.prompt, target_kb=args.target_kb, model_name=args.model)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(raw)
    print(f"✅ 已保存到 {args.out} （{mime}）")


if __name__ == "__main__":
    main()
