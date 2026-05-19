#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from exam_paper_parser import (
    ExamPaper,
    Rect,
    find_largest_blank_rect_in_rect,
)


EXAM_DIR = Path("exam-data/53quiz_sample")
PAGE_NO = 1
SEARCH_RECT = Rect(
    x_min=415.5224,
    y_min=0.0,
    x_max=443.09202,
    y_max=838.98,
)
OUT_PATH = Path("exam-data/find_rect_debug_marked.png")


def main() -> int:
    exam_paper = ExamPaper(EXAM_DIR)
    binary = exam_paper.get_soft_binary_image(PAGE_NO)
    page_width, page_height = binary.shape[1] / exam_paper.scale_x, binary.shape[0] / exam_paper.scale_y
    search_pixel_rect = exam_paper.pdf_rect_to_pixel_rect(SEARCH_RECT)
    result = find_largest_blank_rect_in_rect(binary, search_pixel_rect)
    result_pdf_rect = exam_paper.pixel_rect_to_pdf_rect(result) if result is not None else None

    print(f"exam_dir={EXAM_DIR}")
    print(f"page_no={PAGE_NO}")
    print(f"page_width={page_width} page_height={page_height}")
    print(f"input_pdf={SEARCH_RECT}")
    print(f"input_pixel={search_pixel_rect}")
    print(f"result_pixel={result}")
    print(f"result_pdf={result_pdf_rect}")

    marked = Image.fromarray((~binary).astype(np.uint8) * 255, mode="L").convert("RGB")
    draw = ImageDraw.Draw(marked)
    draw.rectangle(
        (
            search_pixel_rect.left,
            search_pixel_rect.top,
            search_pixel_rect.right,
            search_pixel_rect.bottom,
        ),
        outline="blue",
        width=2,
    )
    draw.text(
        (search_pixel_rect.left + 3, search_pixel_rect.top + 3),
        f"win {search_pixel_rect.left},{search_pixel_rect.top}",
        fill="blue",
    )
    draw.text(
        (max(0, search_pixel_rect.right - 90), max(0, search_pixel_rect.bottom - 16)),
        f"{search_pixel_rect.right},{search_pixel_rect.bottom}",
        fill="blue",
    )
    if result is not None:
        draw.rectangle(
            (result.left, result.top, result.right, result.bottom),
            outline="red",
            width=3,
        )
        draw.text((result.left + 3, result.top + 3), f"{result.left},{result.top}", fill="red")
        draw.text((max(0, result.right - 60), max(0, result.bottom - 16)), f"{result.right},{result.bottom}", fill="red")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    marked.save(OUT_PATH)
    print(f"saved={OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
