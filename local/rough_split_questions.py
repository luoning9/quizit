#!/usr/bin/env python3
"""
粗切入口。

流程只保留三步：
1. 调用 `split_columns_questions` 完成题目分割。
2. 调用 `split_question_bands` 完成题内块划分。
3. 输出裁切图片和 manifest。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

from split_columns_layout import (
    Line,
    PageLayout,
    analyze_page_layout,
    assign_column,
    get_total_pages,
    lines_in_rect,
    parse_pages_spec,
)
from split_columns_questions import ColumnQuestionSplitter
from split_question_bands import split_question_from_columns_question

DEFAULT_OUT_DIR = Path("tmp/question_crops")


def build_part_name(page_no: int, question_no: str, index: int) -> str:
    base = f"p{page_no:03d}_q{int(question_no):02d}"
    return f"{base}.png" if index == 1 else f"{base}_{index}.png"


def normalize_text(lines: Sequence[Line]) -> str:
    ordered = sorted(lines, key=lambda line: (round(line.y_min, 1), line.x_min))
    return "\n".join(line.text for line in ordered)


def save_debug_overlay(
    image: Image.Image,
    output_path: Path,
    scale_x: float,
    scale_y: float,
    rects: Sequence[tuple[str, float, float, float, float]],
) -> None:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for label, x_min, y_min, x_max, y_max in rects:
        draw.rectangle(
            (
                int(x_min * scale_x),
                int(y_min * scale_y),
                int(x_max * scale_x),
                int(y_max * scale_y),
            ),
            outline="red",
            width=4,
        )
        draw.text((int(x_min * scale_x) + 6, int(y_min * scale_y) + 6), label, fill="red")
    overlay.save(output_path)


def process_page(
    layout: PageLayout,
    splitter: ColumnQuestionSplitter,
    image_path: Path | None,
    crops_dir: Path,
    debug_dir: Path | None,
    *,
    dpi: int,
) -> list[dict]:
    if not layout.is_exam_page:
        return []

    page_record = splitter.compute_columns_and_questions(layout.page_no)
    questions = page_record.get("questions", [])
    if not questions:
        return []

    outputs: list[dict] = []
    debug_rects: list[tuple[str, float, float, float, float]] = []

    with tempfile.TemporaryDirectory(prefix="rough_split_questions_") as question_tmp:
        question_tmp_dir = Path(question_tmp)

        for question in questions:
            question_no = str(question["question_no"])
            question_bbox = question["bbox"]

            crop_lines = lines_in_rect(
                layout.lines,
                question_bbox["x_min"],
                question_bbox["x_max"],
                question_bbox["y_min"],
                question_bbox["y_max"],
            )
            ocr_text = normalize_text(crop_lines)

            section_title = question.get("section", "")
            anchor_text = question.get("anchor_text", "")
            final_images: list[dict] = []
            part_index = 1
            question_image = splitter.get_question_image(question["question_id"])
            question_path = question_tmp_dir / f"{question['question_id']}.png"
            question_image.save(question_path, dpi=(dpi, dpi))
            split_result = split_question_from_columns_question(
                question_path,
                {
                    "question_id": question["question_id"],
                    "question_no": question_no,
                },
                dpi=dpi,
                text_source="surya",
            )
            merged_bands = split_result.get("merged_bands") or []

            if not merged_bands:
                output_name = build_part_name(layout.page_no, question_no, part_index)
                question_image.save(crops_dir / output_name)
                final_images.append(
                    {
                        "path": str(Path("images") / output_name),
                        "type": "body",
                    }
                )
                part_index += 1
            else:
                for band in merged_bands:
                    band_bbox = band["bbox"]
                    scale = dpi / 72.0
                    left_px = max(0, int(round(float(band_bbox["x_min"]) * scale)))
                    right_px = min(question_image.width, int(round(float(band_bbox["x_max"]) * scale)))
                    top_px = max(0, int(round(float(band_bbox["y_min"]) * scale)))
                    bottom_px = min(question_image.height, int(round(float(band_bbox["y_max"]) * scale)))
                    if right_px <= left_px or bottom_px <= top_px:
                        continue

                    output_name = build_part_name(layout.page_no, question_no, part_index)
                    question_image.crop((left_px, top_px, right_px, bottom_px)).save(crops_dir / output_name)

                    band_kind = band.get("kind", "body")
                    image_type = "body" if band_kind == "body" else "table" if band_kind == "table" else "visual"
                    final_images.append(
                        {
                            "path": str(Path("images") / output_name),
                            "type": image_type,
                        }
                    )
                    part_index += 1

            debug_rects.append(
                (
                    f"Q{question_no}",
                    question_bbox["x_min"],
                    question_bbox["y_min"],
                    question_bbox["x_max"],
                    question_bbox["y_max"],
                )
            )

            outputs.append(
                {
                    "page": layout.page_no,
                    "question_no": question_no,
                    "section": section_title,
                    "images": final_images,
                    "anchor_text": anchor_text,
                    "ocr_text": ocr_text,
                }
            )

    if debug_dir is not None and debug_rects and image_path is not None:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            scale_x = image.width / layout.page_width if layout.page_width > 0 else 1.0
            scale_y = image.height / layout.page_height if layout.page_height > 0 else 1.0
            debug_path = debug_dir / f"page_{layout.page_no:03d}_overlay.png"
            save_debug_overlay(image, debug_path, scale_x, scale_y, debug_rects)

    return sorted(outputs, key=lambda item: (item["page"], int(item["question_no"])))


def build_page_manifest(layout: PageLayout) -> dict:
    anchors_by_column = {column.index + 1: 0 for column in layout.columns}
    for anchor in layout.anchors:
        column = assign_column(anchor.x_min, layout.columns)
        if column is not None:
            anchors_by_column[column.index + 1] += 1

    return {
        "page": layout.page_no,
        "is_exam_page": layout.is_exam_page,
        "column_count": len(layout.columns),
        "column_starts": [round(column.start_x, 2) for column in layout.columns],
        "question_anchor_count": len(layout.anchors),
        "question_numbers": [anchor.question_no for anchor in layout.anchors],
        "anchors_per_column": anchors_by_column,
        "sections": [section.title for section in layout.sections],
        "reasons": layout.reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="按题号粗切试卷 PDF")
    parser.add_argument("pdf", help="源 PDF 路径")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help="输出目录，默认当前目录 tmp/question_crops",
    )
    parser.add_argument(
        "--pages",
        default="all",
        help="页码范围，如 8-9,12；默认 all",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="页面渲染 DPI，默认 180",
    )
    parser.add_argument(
        "--debug-overlay",
        action="store_true",
        help="额外输出带框选标记的整页预览图",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    crops_dir = out_dir / "images"
    debug_dir = out_dir / "debug" if args.debug_overlay else None

    if not pdf_path.exists():
        print(f"❌ PDF 不存在: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    total_pages = get_total_pages(pdf_path)
    pages = parse_pages_spec(args.pages, total_pages)

    crops_dir.mkdir(parents=True, exist_ok=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    page_manifest: list[dict] = []

    with ColumnQuestionSplitter(pdf_path, dpi=args.dpi, out_dir=out_dir) as splitter:
        if debug_dir is not None:
            for page_no in pages:
                layout = analyze_page_layout(pdf_path, page_no)
                page_manifest.append(build_page_manifest(layout))
                if not layout.is_exam_page:
                    continue
                manifest.extend(
                    process_page(
                        layout,
                        splitter,
                        splitter.get_rendered_page_path(page_no),
                        crops_dir,
                        debug_dir,
                        dpi=args.dpi,
                    )
                )
        else:
            for page_no in pages:
                layout = analyze_page_layout(pdf_path, page_no)
                page_manifest.append(build_page_manifest(layout))
                if not layout.is_exam_page:
                    continue

                manifest.extend(
                    process_page(
                        layout,
                        splitter,
                        None,
                        crops_dir,
                        debug_dir,
                        dpi=args.dpi,
                    )
                )

    manifest_path = out_dir / "manifest.json"
    page_manifest_path = out_dir / "page_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    page_manifest_path.write_text(json.dumps(page_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pages: {pages}")
    print(f"exam_pages: {sum(1 for item in page_manifest if item['is_exam_page'])}")
    print(f"questions: {len(manifest)}")
    print(f"page_manifest: {page_manifest_path}")
    print(f"manifest: {manifest_path}")
    print(f"images: {crops_dir}")


if __name__ == "__main__":
    main()
