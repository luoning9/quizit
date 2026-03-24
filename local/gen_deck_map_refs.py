#!/usr/bin/env python3
"""
根据 deck title 从 Supabase 读取该 deck 的所有卡片，生成引用地图册的文件（可上传到 storage）。
地图册的存储地址是<storage>:quizit_big_medias/geo_8_1/page_*.pdf, *代表页码，从1开始

环境变量（或 .env.local）：
  VITE_SUPABASE_URL
  VITE_SUPABASE_ANON_KEY
  OPENAI_API_KEY
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Dict

from openai import OpenAI, APIError

from quizit_storage import (
    load_env,
    upload_to_storage,
    fetch_cards_by_deck_title,
    find_deck_by_title,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP_INDEX_PATH = REPO_ROOT / "docs" / "geography_8a_maps.md"
MAP_INDEX_HEADER = "章节标题,图片名称,页码,位置"


def get_openai_client(env: Dict[str, str]) -> Optional[OpenAI]:
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        print("⚠️ 未设置 OPENAI_API_KEY，将跳过在线生成", file=sys.stderr)
        return None
    return OpenAI(api_key=api_key)

def load_map_index_csv() -> str:
    if not MAP_INDEX_PATH.exists():
        print(f"❌ 未找到地图索引文件：{MAP_INDEX_PATH}", file=sys.stderr)
        sys.exit(1)

    text = MAP_INDEX_PATH.read_text(encoding="utf-8")
    lines = [line.rstrip() for line in text.splitlines()]

    try:
        header_index = next(i for i, line in enumerate(lines) if line.strip() == MAP_INDEX_HEADER)
    except StopIteration:
        print(
            f"❌ 地图索引文件格式不正确，未找到表头“{MAP_INDEX_HEADER}”：{MAP_INDEX_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)

    csv_lines = [line.strip() for line in lines[header_index:] if line.strip()]
    if len(csv_lines) <= 1:
        print(f"❌ 地图索引文件中没有有效数据：{MAP_INDEX_PATH}", file=sys.stderr)
        sys.exit(1)
    return "\n".join(csv_lines)


def build_system_prompt(map_index_csv: str) -> str:
    return f'''
你是一名初中地理教师。我将提供给你一张知识卡片的内容，你需要根据我给出的《地图册图片索引表》为该卡片挑选出相关的图片。

下面是 csv 格式的《地图册图片索引表》：

{map_index_csv}

---

任务要求如下：

1. 从索引表中自动选择 **1～3 张最符合卡片核心知识点** 的地图。
2. 输出格式必须是 JSON 数组。
3. 每个元素必须使用以下固定结构（map_file 固定为 "geo_8_1"）：

{{
  "map_file": "geo_8_1",
  "name": "<图片名称>",
  "page": <页码数字>,
  "position": "<图片在该页的位置>"
}}

4. 严格只输出 JSON，不要解释过程，不要加入多余文字。
5. 如果挑出多张图片，这些图片跟内容的相关度应基本一致，否则就只输出相关性最高的那一张图片。

'''
def generate_map_ref_prompt(card_info: str) -> str:
    return f'''
请根据下面的卡片内容，从《地图册图片索引表》挑出密切相关的图片，自动生成关联图片数组：
[卡片内容]
    {card_info}'''

def make_map_refs(
    oa_client: OpenAI,
    system_prompt: str,
    keyword: str,
    model: str,
) -> Optional[str]:
    if not keyword:
        return None
    try:
        resp = oa_client.responses.create(
            model=model,
            input=f"{system_prompt}\n\n{generate_map_ref_prompt(keyword)}",
        )
    except APIError as e:
        print(f"⚠️ 调用 OpenAI 失败（{keyword}）: {e}", file=sys.stderr)
        return None

    text = getattr(resp, "output_text", None)
    if not text and getattr(resp, "output", None):
        try:
            for item in resp.output:
                if hasattr(item, "content"):
                    for part in item.content:
                        if getattr(part, "type", "") == "output_text":
                            text = getattr(part, "text", None)
                            if text:
                                break
                if text:
                    break
        except Exception:
            text = None
    return text


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="根据 deck title 获取 deck 内的所有卡片，并生成地图册引用文件back.map存放在后端")
    parser.add_argument("--title", required=True, help="deck 的 title，需精确匹配")
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI 模型，默认 gpt-5-mini")
    args = parser.parse_args(argv)

    if "地理" not in args.title:
        print(f"❌ deck title 应包含“地理”，请确认是否输入错误：{args.title}", file=sys.stderr)
        sys.exit(1)

    env = load_env()
    oa_client = get_openai_client(env)
    map_index_csv = load_map_index_csv()
    system_prompt = build_system_prompt(map_index_csv)
    cards = fetch_cards_by_deck_title(args.title)
    if not cards:
        print(f"未找到 deck 或该 deck 无卡片：{args.title}")
        sys.exit(0)
    deck = find_deck_by_title(args.title)

    cache_dir = Path("tmp/maps")
    cache_dir.mkdir(parents=True, exist_ok=True)

    ordered = []
    for card in cards:
        cid = card["id"]
        front = card.get("front")
        assert front

        print(f"processing {front} ...")
        map_path = cache_dir / f"{cid}.map"
        map_ref_text: Optional[str]
        if map_path.exists():
            map_ref_text = map_path.read_text(encoding="utf-8")
            print("found local map ref file")
        elif oa_client:
            map_ref_text = make_map_refs(
                oa_client,
                system_prompt,
                f"{front}:{card.get('back') or ''}",
                args.model,
            )
        else:
            print(f"⚠️ 未提供 OpenAI 配置且本地无 {map_path.name}，跳过 {cid}")
            map_ref_text = None
        if map_ref_text:
            if not map_path.exists():
                map_path.write_text(map_ref_text, encoding="utf-8")
            map_ref_parsed = None
            try:
                map_ref_parsed = json.loads(map_ref_text)
            except Exception:
                map_ref_parsed = None

            if isinstance(map_ref_parsed, list):
                valid_refs = []
                for idx, ref in enumerate(map_ref_parsed):
                    if not isinstance(ref, dict):
                        print(f"⚠️ map ref #{idx} 不是对象，已跳过 ({cid})")
                        continue
                    if not all(k in ref for k in ("map_file", "name", "page", "position")):
                        print(f"⚠️ map ref #{idx} 缺少字段，已跳过 ({cid})")
                        continue
                    ref_content = json.dumps(ref, ensure_ascii=False, indent=2)
                    upload_to_storage(cid, ref_content.encode("utf-8"), f"back{idx}.map")
                    valid_refs.append(ref)
                if valid_refs:
                    card = dict(card)
                    card["map"] = valid_refs
                    print(f"map refs saved to card {cid} ({len(valid_refs)} files).")
                else:
                    print(map_ref_text)
                    print(f"{front}:{card.get('back') or ''}")
                    print(f"⚠️ 未找到有效 map ref，未上传 ({cid})")
            else:
                upload_to_storage(cid, map_ref_text.encode("utf-8"), "back.map")
                print(f"map ref saved to card {cid}.")
                card = dict(card)
                card["map"] = map_ref_text
        ordered.append(card)

    print(json.dumps({
        "title": deck["title"] if deck else args.title,
        "count": len(ordered),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
