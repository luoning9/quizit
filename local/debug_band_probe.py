#!/usr/bin/env python3
"""
调试指定题目的 band 切分结果。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from split_columns_layout import analyze_page_layout, render_page_image
from split_columns_questions import compute_page_columns_and_questions
from split_question_bands import (
    QuestionPage,
    compute_question_text_height,
    load_surya_detect_lines,
    sanitize_bands_for_json,
    split_question_segment_bands,
)

DEFAULT_OUT_DIR = Path("tmp/debug_band_probe")


def build_question_page(layout: object, image_path: Path) -> QuestionPage:
    with Image.open(image_path) as image:
        dpi_x = round(image.width / layout.page_width * 72.0, 4) if layout.page_width > 0 else 180.0
        dpi_y = round(image.height / layout.page_height * 72.0, 4) if layout.page_height > 0 else 180.0
    return QuestionPage(
        page_no=layout.page_no,
        page_width=layout.page_width,
        page_height=layout.page_height,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
    )


def draw_segment_overlay(image: Image.Image, bands: list[dict], output_path: Path) -> None:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    color_map = {
        "body": "green",
        "label": "orange",
        "table": "blue",
        "empty_gap": "gray",
        "line_gap": "purple",
        "visual_gap": "red",
        "table_gap": "blue",
    }
    for band in bands:
        bbox = band["bbox"]
        color = color_map.get(band["kind"], "blue")
        draw.rectangle(
            (
                int(bbox["x_min"]),
                int(bbox["y_min"]),
                int(bbox["x_max"]),
                int(bbox["y_max"]),
            ),
            outline=color,
            width=3,
        )
        draw.text((int(bbox["x_min"]) + 4, int(bbox["y_min"]) + 2), f'{band["index"]}:{band["kind"]}', fill=color)
    overlay.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="单题 band 调试")
    parser.add_argument("pdf", help="PDF 路径")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--question", default="9")
    parser.add_argument("--question-end", default=None)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = analyze_page_layout(pdf_path, args.page)
    image_path = render_page_image(pdf_path, args.page, out_dir, args.dpi)
    page_image = Image.open(image_path).convert("RGB")
    page_record = compute_page_columns_and_questions(layout, image_path)
    page_qp = build_question_page(layout, image_path)

    surya_lines = load_surya_detect_lines({args.page: image_path}, {args.page: page_qp}).get(args.page) or []
    page_scan_lines = surya_lines or layout.lines
    question_text_height = compute_question_text_height(page_scan_lines)

    start_q = int(args.question)
    end_q = int(args.question_end) if args.question_end is not None else start_q
    selected_questions = [
        item
        for item in page_record["questions"]
        if start_q <= int(item["question_no"]) <= end_q
    ]

    if not selected_questions:
        raise RuntimeError("question not found")

    for question in selected_questions:
        question_no = int(question["question_no"])
        for seg_idx, segment in enumerate(question["segments"], 1):
            split_result = split_question_segment_bands(
                page_qp,
                page_image,
                segment,
                page_scan_lines,
                question_text_height,
            )
            bands = split_result["bands"]
            merged_bands = split_result["merged_bands"]

            suffix = f"q{question_no:02d}_s{seg_idx:02d}"
            json_path = out_dir / f"page_{args.page:03d}_{suffix}_bands.json"
            merged_json_path = out_dir / f"page_{args.page:03d}_{suffix}_merged_bands.json"
            img_path = out_dir / f"page_{args.page:03d}_{suffix}_bands.png"
            merged_img_path = out_dir / f"page_{args.page:03d}_{suffix}_merged_bands.png"

            local_bbox = segment.get("local_bbox", segment["bbox"])
            crop_left = int(float(local_bbox["x_min"]))
            crop_top = int(float(local_bbox["y_min"]))
            crop_right = int(float(local_bbox["x_max"]))
            crop_bottom = int(float(local_bbox["y_max"]))
            crop = page_image.crop((crop_left, crop_top, crop_right, crop_bottom))

            draw_segment_overlay(crop, bands, img_path)
            draw_segment_overlay(crop, merged_bands, merged_img_path)

            json_path.write_text(
                json.dumps({"bands": sanitize_bands_for_json(bands)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            merged_json_path.write_text(
                json.dumps({"bands": merged_bands}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print(f"bands_json: {json_path}")
            print(f"bands_image: {img_path}")
            print(f"merged_bands_json: {merged_json_path}")
            print(f"merged_bands_image: {merged_img_path}")

            bands_dir = out_dir / f"page_{args.page:03d}_{suffix}_band_crops"
            bands_dir.mkdir(parents=True, exist_ok=True)
            for band in bands:
                bbox = band["bbox"]
                left = max(0, int(float(bbox["x_min"])))
                top = max(0, int(float(bbox["y_min"])))
                right = min(page_image.width, int(float(bbox["x_max"])))
                bottom = min(page_image.height, int(float(bbox["y_max"])))
                band_crop = page_image.crop((left, top, right, bottom)).convert("RGB")
                band_path = bands_dir / f'band_{band["index"]:02d}_{band["kind"]}.png'
                band_crop.save(band_path)

            for band in bands:
                print(
                    f'{band["index"]:02d} {band["band_type"]:>4} {band["kind"]:<11} '
                    f'up={int(band.get("connect_up", False))} down={int(band.get("connect_down", False))} '
                    f'{band["bbox"]["y_min"]:.2f}-{band["bbox"]["y_max"]:.2f} {band.get("text", "")}'
                )
            print("--- merged bands ---")
            for idx, item in enumerate(merged_bands, 1):
                bbox = item["bbox"]
                print(
                    f'{idx:02d} {item["kind"]:<11} {bbox["y_min"]:.2f}-{bbox["y_max"]:.2f} '
                    f'members={item.get("member_indices", [])} {item.get("text", "")}'
                )


if __name__ == "__main__":
    main()
