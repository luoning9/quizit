#!/usr/bin/env python3
"""
从指定 vector store 获取材料摘要的 CLI。

示例：
  python summary_vs.py --store-id vs_xxx --prompt "请用中文总结关键要点"
"""

import argparse
import os
import sys
import json
from pathlib import Path
from typing import Optional

from openai import OpenAI, APIError

ENV_LOCAL_PATH = Path(__file__).resolve().parent.parent / ".env.local"

def summarize_knowledge_prompt(keyword: str) -> str:
    assert str
    return f'''
        请从我提供的教材章节内容中，自动抽取该章节的“核心知识点列表”。要求如下：

        1. 输出格式必须是一个 JSON 数组，每个元素包含：
           - "name": 知识点名称
           - "type": 类型（必须是以下三类之一：“事件”“人物与组织”“历史因素”）

        2. 只抽取真正构成知识体系的核心知识点，必须符合以下标准：
           【事件】—— 发生在明确时间地点、有明确过程的历史事件；例如战争、条约签订、改革、运动、政变。
           【人物与组织】—— 本章出现的明确历史人物或成规模、具有历史作用的组织、集团、派别。
           【历史因素】—— 具有清晰概念、贯穿性或推动性影响的思想、政策、制度或历史现象，例如“洋务运动”“列强瓜分中国狂潮”“清末新政”“门户开放政策”。

        3. 不要列入以下内容：
           - 章节中贯穿出现但不是独立“知识点”的描述性句子，如“民族危机加剧”“半殖民地化加深”“自强求富目标”等。
           - 章节总结性的评价性结论，例如“中国开始沦为半殖民地半封建社会”“统治危机加剧”。
           - 具体人物的行为细节、课后活动问题、材料阅读、插图说明。
           - 模糊或过宽泛的抽象概念，除非教材明确以专有名词形式出现。

        4. 确保知识点名称必须与教材中的标准表述一致，不得创造新概念。

        5. 不要输出解释、说明、推理过程，只输出最终的 JSON 数组。

        下面是章节内容，请抽取知识点列表：
        {keyword}
   '''


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


def summarize(store_id: str, keyword: str, model: str, max_tokens: int) -> None:
    client = OpenAI(api_key=load_api_key())
    try:
        resp = client.responses.create(
            model=model,
            input=f"{summarize_knowledge_prompt(keyword)}",
            max_output_tokens=max_tokens,
            tools=[{"type": "file_search", "vector_store_ids": [store_id]}],
        )
    except APIError as e:
        print(f"❌ 调用接口失败: {e}", file=sys.stderr)
        sys.exit(1)

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

    if text:
        # 尝试解析 JSON 输出
        try:
            parsed = json.loads(text)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            # 若不是合法 JSON，包装成预期结构
            print(json.dumps({"summary": text, "keywords": []}, ensure_ascii=False, indent=2))
    else:
        print("未获得文本回复，原始响应：")
        print(resp)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 vector store 获取材料摘要")
    parser.add_argument("--store-id", required=True, help="vector store id，例如 vs_xxx")
    parser.add_argument("--keyword", required=True, help="关键词")
    parser.add_argument("--model", default="gpt-5-mini", help="模型名称，默认 gpt-5-mini")
    parser.add_argument("--max-tokens", type=int, default=8000, help="最大输出 tokens，默认 8000")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    summarize(args.store_id, args.keyword, args.model, args.max_tokens)


if __name__ == "__main__":
    main()
