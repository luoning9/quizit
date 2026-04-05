#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from exam_paper_parser import ExamPaper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打印指定试卷题目的 part 列表")
    parser.add_argument("work_dir", type=Path, help="试卷工作目录")
    parser.add_argument("page_no", type=int, help="页号")
    parser.add_argument("question_no", type=int, help="题号")
    parser.add_argument(
        "-g",
        "--generate-image",
        action="store_true",
        help="生成题目图片并保存为 q<page_no>_<question_no>.png",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("exam-data"),
        help="图片输出目录，默认 exam-data",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    try:
        exam_paper = ExamPaper(args.work_dir)
        question = exam_paper.get_question(args.page_no, args.question_no)
        saved_path: Path | None = None
        if args.generate_image:
            image = exam_paper.create_question_image(args.page_no, args.question_no)
            output_dir = args.out
            output_dir.mkdir(parents=True, exist_ok=True)
            saved_path = output_dir / f"q{args.page_no}_{args.question_no}.png"
            image.save(saved_path)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(question.part_ids)
    print(question.text)
    if saved_path is not None:
        print(f"图片已保存到: {saved_path}")


if __name__ == "__main__":
    main()
