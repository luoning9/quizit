#!/usr/bin/env python3
"""
独立执行“分栏 + 分题”。

输出：
- page_manifest.json：每页的分栏与分题结果
- overlays/page_XXX_columns_questions.png：整页叠图
- rendered_pages/page_XXX.png：页面渲染图
- 可选导出 questions/<question_id>.pdf：指定题目的单页 PDF

设计约束：
- 这个模块只做版面层级的“分栏 + 分题”。
- 不做题内 band 切分，不做 body/table/visual 细分。
- 不依赖 Surya；仅使用 PDF 文字层题号锚点 + 页面渲染图 + soft 二值图。

分栏规则：
1. 先用题号锚点的 x 坐标聚类，确定栏数与初始横向栏位。
2. 对每一栏，取该栏题号最小 x 值 `anchor_min`。
3. 在 `anchor_min` 左侧，用 soft 二值图找最大空白矩形：
   - 该矩形右边作为本栏左边缘；
   - 非第一栏时，该矩形左边作为前一栏右边缘。
4. 栏顶/栏底再用同一套 soft 二值图精修：
   - 找贴顶/贴底、且覆盖整栏宽度的空白矩形；
   - 用它们去掉栏上沿/下沿的连续空白。

分题规则：
1. 每道题的左右边直接使用所属栏的左右边。
2. 对每个题号锚点，在 `anchor.y_min - 8` 到 `anchor.y_min + 2` 的整栏条带上，
   用 soft 二值图找最下面的连续空白区。
3. 当前题上沿取该空白区的 bottom。
4. 当前题下沿取下一题空白区的 top 再减 `0.6pt`；
   如果是该栏最后一题，则取栏底。

输出结构：
- 每道题使用 `(page, question_no)` 唯一定位。
- 同时提供稳定字段：
  - `question_id = p{page:03d}_q{question_no:02d}`
- 题目对象包含：
  - `bbox`：本栏中的主题目框
  - `segments`：该题的所有页面片段

跨栏题导出：
- 当某栏的第一道题上方仍有区域时，这段区域归到前一栏最后一道题，记为 `column_continuation`。
- 导出指定题目 PDF 时，会按 `segments` 顺序自上而下拼接成单页。
- 多个 segment 之间保留 `3pt` 空白。

典型用法：
1. 只生成分栏分题结果：
   `python3 local/split_columns_questions.py input.pdf --out tmp/columns_questions`
2. 额外导出单题 PDF：
   `python3 local/split_columns_questions.py input.pdf --out tmp/columns_questions --export-question-id p001_q10`
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from rough_split_questions import (
    Column,
    Line,
    PageLayout,
    Section,
    analyze_page_layout,
    assign_column,
    clamp,
    compute_effective_columns_and_vertical_bounds,
    find_question_blank_region_from_anchor,
    get_total_pages,
    parse_pages_spec,
    render_page_image,
)


def compute_page_columns_and_questions(
    layout: PageLayout,
    image_path: Path,
) -> dict:
    image = Image.open(image_path)
    scale_x = image.width / layout.page_width
    scale_y = image.height / layout.page_height

    anchors_by_column: dict[int, list] = {column.index: [] for column in layout.columns}
    sections_by_column: dict[int, list[Section]] = {column.index: [] for column in layout.columns}
    for anchor in layout.anchors:
        column = assign_column(anchor.x_min, layout.columns)
        if column is not None:
            anchors_by_column[column.index].append(anchor)
    for section in layout.sections:
        column = assign_column(section.x_min, layout.columns)
        if column is not None:
            sections_by_column[column.index].append(section)

    effective_columns_by_index, column_vertical_bounds = compute_effective_columns_and_vertical_bounds(
        layout.columns,
        image,
        layout.lines,
        layout.footer_top,
        anchors_by_column,
        scale_x,
        scale_y,
    )
    columns = [effective_columns_by_index.get(column.index, column) for column in layout.columns]

    page_record = {
        "page": layout.page_no,
        "is_exam_page": layout.is_exam_page,
        "page_width": round(layout.page_width, 2),
        "page_height": round(layout.page_height, 2),
        "columns": [],
        "questions": [],
    }

    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min)
        column_top, column_bottom = column_vertical_bounds[column.index]
        anchor_min = min((anchor.x_min for anchor in column_anchors), default=column.x_min)
        page_record["columns"].append(
            {
                "index": column.index + 1,
                "x_min": round(column.x_min, 2),
                "y_min": round(column_top, 2),
                "x_max": round(column.x_max, 2),
                "y_max": round(column_bottom, 2),
                "start_x": round(column.start_x, 2),
                "anchor_min": round(anchor_min, 2),
                "question_numbers": [anchor.question_no for anchor in column_anchors],
            }
        )

        if not column_anchors:
            continue

        question_blank_regions = [
            find_question_blank_region_from_anchor(
                image,
                column,
                anchor.y_min,
                column_top,
                scale_x,
                scale_y,
            )
            for anchor in column_anchors
        ]
        question_blank_tops = [region[0] for region in question_blank_regions]
        question_tops = [region[1] for region in question_blank_regions]

        for idx, anchor in enumerate(column_anchors):
            next_anchor = column_anchors[idx + 1] if idx + 1 < len(column_anchors) else None
            top = question_tops[idx]
            if next_anchor is not None:
                bottom = clamp(question_blank_tops[idx + 1] - 0.6, top + 0.1, column_bottom)
            else:
                bottom = column_bottom

            section_title = ""
            for section in sorted(sections_by_column[column.index], key=lambda item: item.y_min):
                if section.y_min <= anchor.y_min:
                    section_title = section.title

            bbox = {
                "x_min": round(column.x_min, 2),
                "y_min": round(top, 2),
                "x_max": round(column.x_max, 2),
                "y_max": round(bottom, 2),
            }
            page_record["questions"].append(
                {
                    "question_id": f"p{layout.page_no:03d}_q{int(anchor.question_no):02d}",
                    "question_no": anchor.question_no,
                    "page": layout.page_no,
                    "column": column.index + 1,
                    "anchor_text": anchor.text,
                    "section": section_title,
                    "bbox": bbox,
                    "segments": [
                        {
                            "page": layout.page_no,
                            "column": column.index + 1,
                            "bbox": bbox,
                            "kind": "question_body",
                        }
                    ],
                }
            )

    page_record["questions"].sort(key=lambda item: (item["column"], int(item["question_no"])))

    by_column: dict[int, list[dict]] = {}
    for item in page_record["questions"]:
        by_column.setdefault(item["column"], []).append(item)

    for col_idx in range(2, len(columns) + 1):
        current_questions = by_column.get(col_idx, [])
        previous_questions = by_column.get(col_idx - 1, [])
        current_column = next((c for c in page_record["columns"] if c["index"] == col_idx), None)
        if not current_questions or not previous_questions or current_column is None:
            continue

        first_question = current_questions[0]
        previous_question = previous_questions[-1]
        continuation_bbox = {
            "x_min": round(current_column["x_min"], 2),
            "y_min": round(current_column["y_min"], 2),
            "x_max": round(current_column["x_max"], 2),
            "y_max": round(first_question["bbox"]["y_min"], 2),
        }
        if continuation_bbox["y_max"] <= continuation_bbox["y_min"] + 0.1:
            continue

        previous_question["segments"].append(
            {
                "page": layout.page_no,
                "column": col_idx,
                "bbox": continuation_bbox,
                "kind": "column_continuation",
            }
        )

    return page_record


def draw_page_overlay(
    image_path: Path,
    page_record: dict,
    output_path: Path,
) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    page_width = float(page_record.get("page_width", image.width))
    page_height = float(page_record.get("page_height", image.height))
    columns = page_record["columns"]
    questions = page_record["questions"]
    scale_x = image.width / page_width if page_width > 0 else 1.0
    scale_y = image.height / page_height if page_height > 0 else 1.0

    for column in columns:
        draw.rectangle(
            (
                int(column["x_min"] * scale_x),
                int(column["y_min"] * scale_y),
                int(column["x_max"] * scale_x),
                int(column["y_max"] * scale_y),
            ),
            outline="green",
            width=3,
        )
        draw.text(
            (int(column["x_min"] * scale_x) + 6, int(column["y_min"] * scale_y) + 6),
            f"C{column['index']}",
            fill="green",
        )

    for question in questions:
        bbox = question["bbox"]
        draw.rectangle(
            (
                int(bbox["x_min"] * scale_x),
                int(bbox["y_min"] * scale_y),
                int(bbox["x_max"] * scale_x),
                int(bbox["y_max"] * scale_y),
            ),
            outline="red",
            width=3,
        )
        draw.text(
            (int(bbox["x_min"] * scale_x) + 6, int(bbox["y_min"] * scale_y) + 6),
            f"Q{question['question_no']}",
            fill="red",
        )

    image.save(output_path)


def export_question_pdf(
    page_record: dict,
    rendered_page_path: Path,
    question_id: str,
    output_path: Path,
) -> Path:
    question = next((item for item in page_record["questions"] if item["question_id"] == question_id), None)
    if question is None:
        raise KeyError(f"question not found: {question_id}")

    image = Image.open(rendered_page_path).convert("RGB")
    page_width = float(page_record.get("page_width", image.width))
    page_height = float(page_record.get("page_height", image.height))
    scale_x = image.width / page_width if page_width > 0 else 1.0
    scale_y = image.height / page_height if page_height > 0 else 1.0
    gap_px = max(1, int(round(3.0 * scale_y)))

    segments = sorted(
        question["segments"],
        key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]),
    )
    crops: list[Image.Image] = []
    max_width = 1
    total_height = 0
    for segment in segments:
        bbox = segment["bbox"]
        left = max(0, int(bbox["x_min"] * scale_x))
        top = max(0, int(bbox["y_min"] * scale_y))
        right = min(image.width, int(bbox["x_max"] * scale_x))
        bottom = min(image.height, int(bbox["y_max"] * scale_y))
        if right <= left or bottom <= top:
            continue
        crop = image.crop((left, top, right, bottom))
        crops.append(crop)
        max_width = max(max_width, crop.width)
        total_height += crop.height

    if not crops:
        raise RuntimeError(f"no segments rendered for {question_id}")

    total_height += gap_px * max(0, len(crops) - 1)

    stitched = Image.new("RGB", (max_width, total_height), "white")
    offset_y = 0
    for idx, crop in enumerate(crops):
        stitched.paste(crop, (0, offset_y))
        offset_y += crop.height
        if idx + 1 < len(crops):
            offset_y += gap_px

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stitched.save(output_path, "PDF", resolution=180.0)
    return output_path


def get_question_image(
    page_record: dict,
    rendered_page_path: Path,
    question_id: str,
    *,
    gap_pt: float = 3.0,
) -> Image.Image:
    """
    按照与 export_question_pdf 相同的裁图方式，将指定题目的所有 segment 从渲染图裁出并
    竖向拼接，返回 PIL Image。

    question_id：完整题目 ID，如 "p003_q05"。
    gap_pt：多段之间的空白间距（单位 pt），默认 3pt。
    """
    question = next(
        (item for item in page_record["questions"] if item["question_id"] == question_id),
        None,
    )
    if question is None:
        raise KeyError(f"question not found: {question_id}")

    image = Image.open(rendered_page_path).convert("RGB")
    page_width = float(page_record.get("page_width", image.width))
    page_height = float(page_record.get("page_height", image.height))
    scale_x = image.width / page_width if page_width > 0 else 1.0
    scale_y = image.height / page_height if page_height > 0 else 1.0
    gap_px = max(0, int(round(gap_pt * scale_y)))

    segments = sorted(
        question["segments"],
        key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]),
    )
    crops: list[Image.Image] = []
    for segment in segments:
        bbox = segment["bbox"]
        left = max(0, int(bbox["x_min"] * scale_x))
        top = max(0, int(bbox["y_min"] * scale_y))
        right = min(image.width, int(bbox["x_max"] * scale_x))
        bottom = min(image.height, int(bbox["y_max"] * scale_y))
        if right <= left or bottom <= top:
            continue
        crops.append(image.crop((left, top, right, bottom)))

    if not crops:
        raise RuntimeError(
            f"no segments could be cropped for question "
            f"{question.get('question_id', question_no)}"
        )

    max_width = max(crop.width for crop in crops)
    total_height = sum(crop.height for crop in crops) + gap_px * max(0, len(crops) - 1)
    stitched = Image.new("RGB", (max_width, total_height), "white")
    offset_y = 0
    for idx, crop in enumerate(crops):
        stitched.paste(crop, (0, offset_y))
        offset_y += crop.height
        if idx + 1 < len(crops):
            offset_y += gap_px

    return stitched



class ColumnQuestionSplitter:
    """
    基于 PDF 文件的分栏分题工具类。

    根据 PDF 路径创建实例，按需渲染页面并缓存结果，提供两个主要接口：
    - compute_columns_and_questions(page_no)：返回该页的分栏分题数据（page_record）
    - get_question_image(question_id)：返回指定题目的拼接图（PIL Image）

    支持 with 语句（自动清理临时目录）：
        with ColumnQuestionSplitter(pdf_path) as splitter:
            img = splitter.get_question_image("p003_q05")

    也可传入 out_dir 持久化渲染结果：
        splitter = ColumnQuestionSplitter(pdf_path, out_dir="tmp/rendered")
    """

    def __init__(
        self,
        pdf_path: Path | str,
        *,
        dpi: int = 180,
        out_dir: Path | str | None = None,
    ) -> None:
        self._pdf_path = Path(pdf_path).expanduser().resolve()
        self._dpi = dpi
        self._out_dir = Path(out_dir).expanduser().resolve() if out_dir else None
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._layouts: dict[int, PageLayout] = {}
        self._page_records: dict[int, dict] = {}
        self._image_paths: dict[int, Path] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_dir(self) -> Path:
        """返回渲染图存放目录，必要时创建临时目录。"""
        if self._out_dir is not None:
            render_dir = self._out_dir / "rendered_pages"
            render_dir.mkdir(parents=True, exist_ok=True)
            return render_dir
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="split_columns_")
        render_dir = Path(self._tmp.name) / "rendered_pages"
        render_dir.mkdir(parents=True, exist_ok=True)
        return render_dir

    def _ensure_page(self, page_no: int) -> tuple[PageLayout, Path]:
        """按需解析 layout 并渲染页面图，结果均缓存。"""
        if page_no not in self._layouts:
            self._layouts[page_no] = analyze_page_layout(self._pdf_path, page_no)
        if page_no not in self._image_paths:
            self._image_paths[page_no] = render_page_image(
                self._pdf_path, page_no, self._render_dir(), self._dpi
            )
        return self._layouts[page_no], self._image_paths[page_no]

    def _page_no_from_question_id(self, question_id: str) -> int:
        """从 question_id（如 'p003_q05'）解析页码。"""
        m = re.match(r"p(\d+)_q\d+", question_id)
        if not m:
            raise ValueError(f"无法从 question_id 解析页码: {question_id!r}")
        return int(m.group(1))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute_columns_and_questions(self, page_no: int) -> dict:
        """
        计算并返回指定页的分栏分题数据（page_record）。
        结果会被缓存，同一页号重复调用不会重复计算。
        """
        if page_no not in self._page_records:
            layout, image_path = self._ensure_page(page_no)
            self._page_records[page_no] = compute_page_columns_and_questions(
                layout, image_path
            )
        return self._page_records[page_no]

    def get_question_image(
        self,
        question_id: str,
        *,
        gap_pt: float = 3.0,
    ) -> Image.Image:
        """
        返回指定题目的 PIL Image（各 segment 竖向拼接）。
        question_id 格式如 'p003_q05'，页码由其自动解析。
        """
        page_no = self._page_no_from_question_id(question_id)
        page_record = self.compute_columns_and_questions(page_no)
        _, image_path = self._ensure_page(page_no)
        return get_question_image(page_record, image_path, question_id, gap_pt=gap_pt)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        """释放临时目录（使用持久 out_dir 时无需调用）。"""
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def __enter__(self) -> "ColumnQuestionSplitter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="独立执行分栏分题")
    parser.add_argument("pdf", help="源 PDF 路径")
    parser.add_argument(
        "--out",
        default="tmp/columns_questions",
        help="输出目录，默认 tmp/columns_questions",
    )
    parser.add_argument(
        "--pages",
        default="all",
        help="页码范围，如 1-2,5；默认 all",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="页面渲染 DPI，默认 180",
    )
    parser.add_argument(
        "--export-question-id",
        help="额外导出指定题目的单页 PDF，例如 p001_q10",
    )
    parser.add_argument(
        "--export-question-out",
        help="指定题目 PDF 输出路径；默认写到 out/questions/<question_id>.pdf",
    )
    args = parser.parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    overlays_dir = out_dir / "overlays"

    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    total_pages = get_total_pages(pdf_path)
    pages = parse_pages_spec(args.pages, total_pages)

    out_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)

    page_manifest: list[dict] = []

    with ColumnQuestionSplitter(pdf_path, dpi=args.dpi, out_dir=out_dir) as splitter:
        for page_no in pages:
            page_record = splitter.compute_columns_and_questions(page_no)
            page_manifest.append(page_record)
            _, image_path = splitter._ensure_page(page_no)
            draw_page_overlay(
                image_path,
                page_record,
                overlays_dir / f"page_{page_no:03d}_columns_questions.png",
            )

        export_path: Path | None = None
        if args.export_question_id:
            question_id = args.export_question_id
            export_path = (
                Path(args.export_question_out).expanduser().resolve()
                if args.export_question_out
                else (out_dir / "questions" / f"{question_id}.pdf")
            )
            img = splitter.get_question_image(question_id)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(export_path), "PDF", resolution=float(args.dpi))

    page_manifest_path = out_dir / "page_manifest.json"
    page_manifest_path.write_text(
        json.dumps(page_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"pages: {pages}")
    print(f"page_manifest: {page_manifest_path}")
    print(f"overlays: {overlays_dir}")
    print(f"rendered_pages: {out_dir / 'rendered_pages'}")
    if export_path is not None:
        print(f"question_pdf: {export_path}")


if __name__ == "__main__":
    main()
