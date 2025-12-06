#!/usr/bin/env python3
"""
根据 deck title 从 Supabase 读取该 deck 的所有卡片，生成 GraphViz DOT（可上传到 storage）。

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


def get_openai_client(env: Dict[str, str]) -> OpenAI:
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ 请设置 OPENAI_API_KEY（环境变量或 .env.local）", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=api_key)


def generate_graph_prompt(keyword: str) -> str:
    return f'''
请根据以下规范，为指定历史知识点生成 GraphViz DOT 文件，用于构建紧凑、美观、统一的小型知识图谱。

【全局布局要求】
- 使用 digraph，方向 rankdir=LR（从左到右）
- 背景要透明
- 图整体紧凑：nodesep=0.28，ranksep=0.45
- 使用 splines=true
- 全局字体：fontname="SimSun"，fontsize=14，minfontsize=14

【节点（node）样式】
- shape=box，style="rounded,filled"
- fillcolor="#FAFAFA"，color="#666666"
- fontname="SimSun"，fontsize=14
- margin="0.05,0.04"（极小内边距）
- 中心节点可以包含时间/身份说明
- 其他节点只写名称，不加任何解释

【节点前缀图标（纯 Unicode 黑白线条）】
只在“人物 / 组织 / 事件”节点前加图标：
- 人物（Person）：♙
- 组织（Organization）：⌂
- 事件（Event）：⬟
  其他类型（如思想、制度、条约等）不加图标。

【关系线（edge）样式】
- style=dashed（虚线）
- fontsize=14，labelfontsize=14（强制与节点一致）
- color="#444444"，arrowsize=0.6
- labeldistance=1.2
- 关系线标签长度为 2–10 字，要求简洁、自然、表达准确
  例如：提出、推动、参与、领导、奠基、促成、制定、产生影响等

【cluster 区域（动态自动分组）】
- 区域数量不固定，根据知识点关系自动生成 2–4 个组合合理的区域
- 可能的分组方式示例（根据知识点类型自动调整）：
  对事件：前因 / 背景；参与力量；直接结果；深远影响
  对人物：相关组织；参与事件；提出思想；历史影响
  对思想或制度：形成背景；提出者；影响事件；制度化影响
- cluster 样式：
  style="rounded,filled"
  color="#D0D0D0"
  背景色从以下淡色中任选（可重复）：#EEF8FF / #F2FFF2 / #F9F5E6 / #F4F0FF
- cluster 内部更紧凑：ranksep=0.25，nodesep=0.18
- cluster 标签简短明确（例：“参与的事件”“相关组织”“历史影响”）

【内容选择要求】
- 只包括与中心知识点具有直接关系的节点
- 关系必须符合历史逻辑（如创造、提出、参与、影响、促成、制定等）
- 图要紧凑、清晰、美观，适合在小图中呈现

【输出要求】
- 只输出 DOT 文件内容，不加任何解释、注释或额外文字
- 不使用代码块包裹 DOT，直接输出 DOT 纯文本

【任务】
请根据以上规范，为以下知识点生成 GraphViz DOT 文件：
{keyword}
    '''

def fetch_graph(
    oa_client: OpenAI,
    store_id: str,
    keyword: str,
    model: str,
    max_tokens: int,
) -> Optional[str]:
    if not keyword:
        return None
    try:
        resp = oa_client.responses.create(
            model=model,
            input=generate_graph_prompt(keyword),
            max_output_tokens=max_tokens,
            tools=[{"type": "file_search", "vector_store_ids": [store_id]}],
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
    parser = argparse.ArgumentParser(description="根据 deck title 获取 deck 内的所有卡片，并可调用向量库定义关键词")
    parser.add_argument("--title", required=True, help="deck 的 title，需精确匹配")
    parser.add_argument("--store-id", required=False, help="vector store id，用于查询定义；不提供时不调用 OpenAI")
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI 模型，默认 gpt-5-mini")
    parser.add_argument("--max-tokens", type=int, default=8000, help="定义输出最大 tokens，默认 8000")
    args = parser.parse_args(argv)

    env = load_env()
    oa_client = get_openai_client(env) if args.store_id else None
    cards = fetch_cards_by_deck_title(args.title)
    if not cards:
        print(f"未找到 deck 或该 deck 无卡片：{args.title}")
        sys.exit(0)
    deck = find_deck_by_title(args.title)

    cache_dir = Path("tmp/dots")
    cache_dir.mkdir(parents=True, exist_ok=True)

    ordered = []
    for card in cards:
        cid = card["id"]
        raw_kw = str(card.get("front") or "")
        keyword = raw_kw.strip().splitlines()[-1].strip() if raw_kw.strip() else ""
        if keyword:
            print(f"processing {keyword} ...")
            dot_path = cache_dir / f"{cid}.dot"
            if dot_path.exists():
                graph = dot_path.read_text(encoding="utf-8")
                print("found local graph dot file")
            elif oa_client and args.store_id:
                graph = fetch_graph(
                    oa_client,
                    args.store_id,
                    f"{keyword}:{card.get('back') or ''}",
                    args.model,
                    args.max_tokens,
                )
            else:
                print(f"⚠️ 未提供 store-id 且本地无 {dot_path.name}，跳过 {cid}")
                graph = None
            if graph:
                if not dot_path.exists():
                    dot_path.write_text(graph, encoding="utf-8")
                upload_to_storage(cid, graph.encode("utf-8"), "back.dot")
                print(f"graph saved to card {cid}.")

                card = dict(card)
                card["graph"] = graph
        ordered.append(card)

    print(json.dumps({
        "title": deck["title"] if deck else args.title,
        "count": len(ordered),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
