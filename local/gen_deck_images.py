#!/usr/bin/env python3
"""
按 deck title 扫描各卡片的 back，列出 markdown 图片占位符（![]...），为后续生成图片做准备。

环境变量（或 .env.local）：
  VITE_SUPABASE_URL
  VITE_SUPABASE_ANON_KEY
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from gen_image import generate_image_bytes, guess_subject_from_title
from quizit_storage import fetch_cards_by_deck_title, upload_to_storage  # 同目录引用


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


def extract_back(back_raw: str) -> Tuple[str, List[Tuple[Optional[str], Optional[str]]]]:
    """
    返回 (back_text, image_infos)，只提取 back 字段里的 markdown 图片语法。
    image_infos 元素为 (alt, url)。
    """
    back_text = back_raw or ""
    if back_raw:
        try:
            parsed = json.loads(back_raw)
            if isinstance(parsed, dict):
                # 常见字段：text/answer/back（按优先级尝试）
                for key in ("text", "answer", "back"):
                    if parsed.get(key):
                        back_text = str(parsed[key])
                        break
            elif isinstance(parsed, list):
                back_text = "\n".join(str(x) for x in parsed)
        except Exception:
            # 非 JSON，视为纯文本
            back_text = back_raw

    image_infos = extract_markdown_images(back_text) if back_text else []

    # 去重保持顺序
    seen = set()
    deduped: List[Tuple[Optional[str], Optional[str]]] = []
    for info in image_infos:
        key = (info[0] or "", info[1] or "")
        if key not in seen:
            seen.add(key)
            deduped.append(info)
    return back_text, deduped


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="按 deck title 列出 back 中的图片占位符（![]）")
    parser.add_argument("title", help="decks.title")
    parser.add_argument(
        "--subject",
        choices=["B", "H", "P"],
        help="学科：P(物理)/H(历史)/B(生物)，可选",
    )
    parser.add_argument(
        "--doit",
        action="store_true",
        default=False,
        help="默认仅使用缓存图片，开启后才会调用 AI 生成新图",
    )
    args = parser.parse_args(argv)

    subject = args.subject or guess_subject_from_title(args.title)
    if args.doit and not subject:
        print("❌ 开启 --doit 时必须提供或能猜出 --subject（B/H/P）", file=sys.stderr)
        sys.exit(2)
    cards = fetch_cards_by_deck_title(args.title)
    if not cards:
        print(f"❌ 未找到 deck 或无卡片：{args.title}", file=sys.stderr)
        sys.exit(1)

    if subject:
        hint_suffix = "" if args.subject else "（自动猜测）"
        print(f"🔎 学科: {subject} {hint_suffix}")
        subject_hint = f"（学科: {subject}）"
    else:
        print("🔎 学科: 未提供，且无法猜测")
        subject_hint = ""
    print(f"📃 deck {args.title} back 图片占位符：{subject_hint}")
    found_any = False
    for card in cards:  # 已按 deck.items 顺序返回
        cid = card.get("id")
        back_text, infos = extract_back(card.get("back") or "")
        if not infos:
            continue

        found_any = True
        print(f"- card {cid}:")
        for idx, (alt, url) in enumerate(infos, start=1):
            desc = alt or back_text or "image"
            url_part = f", url={url}" if url else ""
            print(f"    #{idx} desc={desc}{url_part}")

            filename = f"back{idx}.jpg"
            cache_dir = Path("tmp/deck_images_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_path = cache_dir / f"{cid}-{filename}"

            img_bytes: Optional[bytes] = None
            mime = "image/jpeg"

            if local_path.exists():
                img_bytes = local_path.read_bytes()
                print(f"      cache found: {local_path}")
            elif args.doit:
                try:
                    img_bytes, mime = generate_image_bytes(desc, subject=subject)
                    local_path.write_bytes(img_bytes)
                    print(f"      image generated & cached: {local_path}")
                except RuntimeError as e:
                    print(f"⚠️ 生成图片失败（card {cid}, #{idx}, prompt='{desc}'): {e}", file=sys.stderr)
                    continue
            else:
                print(f"      skip (no cache, --doit 未开启)")
                continue

            upload_to_storage(cid, img_bytes, filename, content_type=mime)
            print(f"      done {cid}")

    if not found_any:
        print("ℹ️ 未找到任何图片占位符。")


if __name__ == "__main__":
    main()
