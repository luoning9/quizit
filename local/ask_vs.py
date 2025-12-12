#!/usr/bin/env python3
"""
根据指定 vector store 回答问题的 CLI。

示例：
  python ask_vs.py --store-id vs_xxx --question "海淀黄庄在哪？"
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from openai import OpenAI, APIError

ENV_LOCAL_PATH = Path(__file__).resolve().parent.parent / ".env.local"


def load_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not api_key:
        print("❌ 请设置 OPENAI_API_KEY 环境变量或在 .env.local 中提供。", file=sys.stderr)
        sys.exit(1)
    return api_key


def ask(store_id: str, question: str, model: str, max_tokens: int) -> None:
    client = OpenAI(api_key=load_api_key())
    try:
        resp = client.responses.create(
            model=model,
            input=question,
            max_output_tokens=max_tokens,
            tools=[{"type": "file_search", "vector_store_ids": [store_id]}],
        )
    except APIError as e:
        print(f"❌ 调用接口失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 安全提取文本输出
    text = getattr(resp, "output_text", None)
    if not text and getattr(resp, "output", None):
        try:
            # 尝试从 output 列表提取 text 字段
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

    if text:
        print(text)
    else:
        print("未获得文本回复，原始响应：")
        print(resp)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="根据指定 vector store 回答问题")
    parser.add_argument(
        "--store-id",
        required=True,
        help="vector store id，例如 vs_xxx",
    )
    parser.add_argument(
        "--model",
        default="gpt-5-mini",
        help="模型名称，默认 gpt-5-mini",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8000,
        help="最大输出 tokens，默认 8000",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    while True:
        try:
            question = input("请输入问题（或 Ctrl+C 退出）：").strip()
        except KeyboardInterrupt:
            print("\n已退出。")
            break
        if not question:
            continue
        ask(args.store_id, question, args.model, args.max_tokens)
        print("-" * 40)


if __name__ == "__main__":
    main()
