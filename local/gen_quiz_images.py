#!/usr/bin/env python3
"""
按 quiz title 列出题干中的图片描述，并生成/上传对应图片。

环境变量（或 .env.local）：
  VITE_SUPABASE_URL
  VITE_SUPABASE_ANON_KEY
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from quizit_storage import fetch_cards_by_quiz_title, upload_to_storage  # 同目录引用
from gen_image import generate_image_bytes  # 生成图片接口


def extract_markdown_images(text: str) -> List[Tuple[Optional[str], Optional[str]]]:
    """
    提取 markdown 图片语法：
    - ![alt](url) → (alt, url)
    - ![alt]      → (alt, None)
    """
    results: List[Tuple[Optional[str], Optional[str]]] = []
    i = 0
    while i < len(text):
        bang = text.find("![", i)
        if bang == -1:
            break
        close_bracket = text.find("]", bang + 2)
        if close_bracket == -1:
            break

        alt_text = text[bang + 2 : close_bracket].strip()
        url: Optional[str] = None

        if close_bracket + 1 < len(text) and text[close_bracket + 1] == "(":
            close_paren = text.find(")", close_bracket + 2)
            if close_paren != -1:
                url = text[close_bracket + 2 : close_paren].strip()
                i = close_paren + 1
            else:
                i = close_bracket + 2
        else:
            i = close_bracket + 1

        results.append((alt_text or None, url or None))
    return results


def extract_front(front_raw: str) -> Tuple[str, List[Tuple[Optional[str], Optional[str]]]]:
    """
    返回 (prompt_text, image_infos)，只提取题干中的 markdown 图片语法。
    image_infos 元素为 (alt, url)。
    """
    prompt_text = front_raw or ""
    if not front_raw:
        return prompt_text, []

    try:
        parsed = json.loads(front_raw)
        if isinstance(parsed, dict):
            prompt_text = str(parsed.get("prompt") or "")
    except Exception:
        # 非 JSON，视为纯文本
        pass

    image_infos = extract_markdown_images(prompt_text) if prompt_text else []

    # 去重保持顺序
    seen = set()
    deduped: List[Tuple[Optional[str], Optional[str]]] = []
    for info in image_infos:
        key = (info[0] or "", info[1] or "")
        if key not in seen:
            seen.add(key)
            deduped.append(info)
    return prompt_text, deduped


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="按 quiz title 列出题干中的图片 URL")
    parser.add_argument("title", help="quiz_templates.title")
    parser.add_argument(
        "--doit",
        action="store_true",
        default=False,
        help="默认仅使用缓存图片，开启后才会调用 AI 生成新图",
    )
    parser.add_argument(
        "--subject",
        choices=["B", "H", "P"],
        help="学科：P(物理)/H(历史)/B(生物)；开启 --doit 时必填",
    )
    args = parser.parse_args(argv)

    if args.doit and not args.subject:
        print("❌ 开启 --doit 时必须提供 --subject（B/H/P）", file=sys.stderr)
        sys.exit(2)

    cards = fetch_cards_by_quiz_title(args.title)
    if not cards:
        print(f"❌ 未找到 quiz_template 或无卡片：{args.title}", file=sys.stderr)
        sys.exit(1)

    print(f"📃 模板 {args.title} 题目图片列表：")
    found_any = False
    for card in cards:  # 已按模板顺序返回
        cid = card.get("id")
        prompt_text, infos = extract_front(card.get("front") or "")
        if infos:
            found_any = True
            print(f"- card {cid}:")
            for idx, (alt, url) in enumerate(infos, start=1):
                desc = alt or prompt_text or "image"
                filename = f"front{idx}.jpg"
                cache_dir = Path("tmp/quiz_images_cache")
                cache_dir.mkdir(parents=True, exist_ok=True)
                local_path = cache_dir / f"{cid}-{filename}"

                img_bytes: Optional[bytes] = None
                mime = "image/jpeg"

                if local_path.exists():
                    img_bytes = local_path.read_bytes()
                    print(f"    cache found: {local_path}")
                elif args.doit:
                    try:
                        img_bytes, mime = generate_image_bytes(desc, subject=args.subject)
                        local_path.write_bytes(img_bytes)
                        print(f"    image generated & cached: {local_path}")
                    except RuntimeError as e:
                        print(f"⚠️ 生成图片失败（card {cid}, #{idx}, prompt='{desc}'): {e}", file=sys.stderr)
                        continue
                else:
                    print(f"    skip (no cache, --doit 未开启)")
                    continue

                upload_to_storage(cid, img_bytes, filename, content_type=mime)
                print(f"    done {cid}")
    if not found_any:
        print("ℹ️ 未找到任何图片 URL。")


if __name__ == "__main__":
    main()
