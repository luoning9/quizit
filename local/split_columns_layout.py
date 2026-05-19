#!/usr/bin/env python3
"""
公共的页面布局与分栏基础模块。

这个模块只保留 `split_columns_questions` 需要的最小依赖：
- PDF 文字层解析
- 页面渲染
- 分栏 / 分题所需的布局基础

它不依赖 `rough_split_questions.py`。
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image

QUESTION_RE = re.compile(r"^\s*(\d{1,2})\s*[.．、](?!\d)")
QUESTION_PREFIX_RE = re.compile(r"^(\s*)\d{1,2}(\s*[.．、])")
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+、")
INCOMPLETE_END_RE = re.compile(r"[:：;；,，、=＝\(\[【]\s*$")
STRUCTURE_BREAK_RE = re.compile(
    r"^\s*(?:"
    r"[A-Za-zＡ-Ｚａ-ｚ]\s*[.．、\)]"
    r"|[（(]?\d{1,2}\s*[)）.．、]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]"
    r"|[@＠]"
    r")"
)


@dataclass(frozen=True)
class Line:
    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class Anchor:
    question_no: str
    x_min: float
    y_min: float
    text: str


@dataclass(frozen=True)
class Section:
    title: str
    x_min: float
    y_min: float


@dataclass(frozen=True)
class Column:
    index: int
    x_min: float
    x_max: float
    start_x: float


@dataclass(frozen=True)
class PageLayout:
    page_no: int
    page_width: float
    page_height: float
    lines: list[Line]
    anchors: list[Anchor]
    sections: list[Section]
    columns: list[Column]
    footer_top: float
    is_exam_page: bool
    reasons: list[str]


_COLUMN_DARK_CACHE: dict[tuple[int, int, int, str], np.ndarray] = {}


def run_cmd(args: Sequence[str], *, capture: bool = True) -> str:
    proc = subprocess.run(
        args,
        check=False,
        capture_output=capture,
        text=True,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise RuntimeError(f"command failed: {' '.join(args)}\n{detail}")
    return proc.stdout if capture else ""


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_pages_spec(spec: str | None, total_pages: int) -> list[int]:
    if not spec or spec.lower() == "all":
        return list(range(1, total_pages + 1))

    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))

    valid = sorted(page for page in pages if 1 <= page <= total_pages)
    if not valid:
        raise ValueError("no valid pages selected")
    return valid


def get_total_pages(pdf_path: Path) -> int:
    text = run_cmd(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Pages:\s+(\d+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("failed to parse page count from pdfinfo")
    return int(match.group(1))


def parse_bbox_page(pdf_path: Path, page_no: int) -> tuple[float, float, list[Line]]:
    xml_text = run_cmd(
        [
            "pdftotext",
            "-bbox-layout",
            "-f",
            str(page_no),
            "-l",
            str(page_no),
            str(pdf_path),
            "-",
        ]
    )
    root = ET.fromstring(xml_text)

    page_el = None
    for elem in root.iter():
        if strip_ns(elem.tag) == "page":
            page_el = elem
            break
    if page_el is None:
        raise RuntimeError(f"page {page_no} not found in bbox output")

    page_width = float(page_el.attrib["width"])
    page_height = float(page_el.attrib["height"])

    lines: list[Line] = []
    for elem in root.iter():
        if strip_ns(elem.tag) != "line":
            continue
        words = [child.text or "" for child in elem if strip_ns(child.tag) == "word"]
        text = "".join(words).strip()
        if not text:
            continue
        lines.append(
            Line(
                text=text,
                x_min=float(elem.attrib["xMin"]),
                y_min=float(elem.attrib["yMin"]),
                x_max=float(elem.attrib["xMax"]),
                y_max=float(elem.attrib["yMax"]),
            )
        )
    return page_width, page_height, lines


def overlap_length(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return max(0.0, min(a_max, b_max) - max(a_min, b_min))


def find_question_anchors(lines: Iterable[Line], page_width: float, page_height: float) -> list[Anchor]:
    anchors: list[Anchor] = []
    for line in lines:
        if line.y_min < 20.0:
            continue
        if line.x_min < page_width * 0.03:
            continue
        match = QUESTION_RE.match(line.text)
        if not match:
            continue
        if int(match.group(1)) <= 0:
            continue
        if len(line.text) < 8:
            continue
        anchors.append(
            Anchor(
                question_no=match.group(1),
                x_min=line.x_min,
                y_min=line.y_min,
                text=line.text,
            )
        )
    return anchors


def find_sections(lines: Iterable[Line], page_width: float, page_height: float) -> list[Section]:
    sections: list[Section] = []
    for line in lines:
        if line.y_min < page_height * 0.1 or line.y_min > page_height * 0.95:
            continue
        if line.x_min < page_width * 0.04:
            continue
        if not SECTION_RE.match(line.text):
            continue
        sections.append(Section(title=line.text, x_min=line.x_min, y_min=line.y_min))
    return sections


def cluster_anchor_starts(anchors: Sequence[Anchor], page_width: float) -> list[float]:
    if not anchors:
        return []

    threshold = max(90.0, page_width * 0.08)
    starts = sorted(anchor.x_min for anchor in anchors)
    clusters: list[list[float]] = [[starts[0]]]
    for start in starts[1:]:
        if abs(start - mean(clusters[-1])) <= threshold:
            clusters[-1].append(start)
        else:
            clusters.append([start])
    return [mean(cluster) for cluster in clusters]


def build_columns(column_starts: Sequence[float], page_width: float) -> list[Column]:
    if not column_starts:
        return []

    left_pad = 24.0
    gutter = 18.0
    columns: list[Column] = []
    for index, start_x in enumerate(column_starts):
        x_min = max(0.0, start_x - left_pad)
        if index + 1 < len(column_starts):
            next_start = column_starts[index + 1]
            x_max = min(page_width, next_start - gutter)
        else:
            x_max = page_width - 12.0
        columns.append(Column(index=index, x_min=x_min, x_max=x_max, start_x=start_x))
    return columns


def compute_column_text_bounds(
    column: Column,
    column_anchors: Sequence[Anchor],
    column_lines: Sequence[Line],
) -> tuple[float, float]:
    text_xmin = min((anchor.x_min for anchor in column_anchors), default=column.x_min)
    line_by_text = {line.text: line for line in column_lines}
    text_xmax = max(
        (
            line_by_text.get(anchor.text).x_max
            for anchor in column_anchors
            if line_by_text.get(anchor.text) is not None
        ),
        default=text_xmin,
    )
    return text_xmin, text_xmax


def replace_anchor_question_prefix(text: str, question_no: int) -> str:
    return QUESTION_PREFIX_RE.sub(rf"\1{question_no}\2", text, count=1)


def correct_anchor_numbers(anchors: Sequence[Anchor], columns: Sequence[Column]) -> list[Anchor]:
    if len(anchors) < 3 or not columns:
        return list(anchors)

    indexed = list(enumerate(anchors))
    ordered = sorted(
        indexed,
        key=lambda item: (
            assign_column(item[1].x_min, columns).index if assign_column(item[1].x_min, columns) is not None else 999,
            item[1].y_min,
            item[1].x_min,
        ),
    )
    corrected: list[Anchor] = list(anchors)
    for order_idx in range(1, len(ordered) - 1):
        anchor_idx, anchor = ordered[order_idx]
        prev_anchor = corrected[ordered[order_idx - 1][0]]
        next_anchor = corrected[ordered[order_idx + 1][0]]
        prev_no = int(prev_anchor.question_no)
        curr_no = int(corrected[anchor_idx].question_no)
        next_no = int(next_anchor.question_no)
        expected = prev_no + 1

        if next_no == prev_no + 2 and curr_no != expected:
            corrected[anchor_idx] = Anchor(
                question_no=str(expected),
                x_min=anchor.x_min,
                y_min=anchor.y_min,
                text=replace_anchor_question_prefix(anchor.text, expected),
            )
    return corrected


def assign_column(x_min: float, columns: Sequence[Column]) -> Column | None:
    for column in columns:
        if column.x_min <= x_min <= column.x_max:
            return column
    if not columns:
        return None
    return min(columns, key=lambda column: abs(column.start_x - x_min))


def detect_footer_top(lines: Sequence[Line], page_height: float) -> float:
    _ = lines
    return page_height - 6.0


def analyze_page_layout(pdf_path: Path, page_no: int) -> PageLayout:
    page_width, page_height, lines = parse_bbox_page(pdf_path, page_no)
    anchors = find_question_anchors(lines, page_width, page_height)
    sections = find_sections(lines, page_width, page_height)
    column_starts = cluster_anchor_starts(anchors, page_width)
    columns = build_columns(column_starts, page_width)
    anchors = correct_anchor_numbers(anchors, columns)
    footer_top = detect_footer_top(lines, page_height)

    anchors_by_column: dict[int, int] = {column.index: 0 for column in columns}
    for anchor in anchors:
        column = assign_column(anchor.x_min, columns)
        if column is not None:
            anchors_by_column[column.index] += 1

    reasons: list[str] = []
    column_count = len(columns)
    if column_count not in (2, 3):
        reasons.append(f"column_count={column_count}, not in [2, 3]")

    if not anchors:
        reasons.append("no question anchors detected")

    sparse_columns = [str(column.index + 1) for column in columns if anchors_by_column.get(column.index, 0) == 0]
    if sparse_columns:
        reasons.append(f"empty columns detected: {', '.join(sparse_columns)}")

    if len(anchors) < column_count:
        reasons.append(f"anchor_count={len(anchors)} is lower than column_count={column_count}")

    has_sections = bool(sections)
    if not has_sections and len(anchors) < 4:
        reasons.append("missing section headers and too few anchors")

    is_exam_page = not reasons
    if is_exam_page:
        reasons.append("detected as exam page")

    return PageLayout(
        page_no=page_no,
        page_width=page_width,
        page_height=page_height,
        lines=lines,
        anchors=anchors,
        sections=sections,
        columns=columns,
        footer_top=footer_top,
        is_exam_page=is_exam_page,
        reasons=reasons,
    )


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def lines_in_rect(lines: Iterable[Line], x_min: float, x_max: float, y_min: float, y_max: float) -> list[Line]:
    return [
        line
        for line in lines
        if line.x_max >= x_min and line.x_min <= x_max and line.y_max >= y_min and line.y_min <= y_max
    ]


def has_section_title(lines: Sequence[Line]) -> bool:
    return any(SECTION_RE.match(line.text) for line in lines)


def cluster_lines_vertically(lines: Sequence[Line], max_gap: float = 16.0) -> list[list[Line]]:
    ordered = sorted(lines, key=lambda line: (line.y_min, line.x_min))
    if not ordered:
        return []

    groups: list[list[Line]] = [[ordered[0]]]
    current_bottom = ordered[0].y_max
    for line in ordered[1:]:
        if line.y_min - current_bottom <= max_gap:
            groups[-1].append(line)
            current_bottom = max(current_bottom, line.y_max)
        else:
            groups.append([line])
            current_bottom = line.y_max
    return groups


def bbox_to_px(bbox: dict[str, float], scale_x: float, scale_y: float) -> tuple[int, int, int, int]:
    left = int(bbox["x_min"] * scale_x)
    top = int(bbox["y_min"] * scale_y)
    right = int(bbox["x_max"] * scale_x)
    bottom = int(bbox["y_max"] * scale_y)
    return left, top, right, bottom


def get_clean_dark_crop(
    page_image: Image.Image,
    bbox: dict[str, float],
    scale_x: float,
    scale_y: float,
    pad_y_px: int = 0,
    mode: str = "soft",
) -> np.ndarray | None:
    left, top, right, bottom = bbox_to_px(bbox, scale_x, scale_y)
    if right - left < 2 or bottom - top < 2:
        return None
    top = max(0, top - pad_y_px)
    bottom = min(page_image.height, bottom + pad_y_px)
    if right - left < 2 or bottom - top < 2:
        return None

    cache_key = (id(page_image), left, right, mode)
    column_dark = _COLUMN_DARK_CACHE.get(cache_key)
    if column_dark is None:
        page_gray = np.asarray(page_image.convert("L"))
        column_gray = page_gray[:, left:right]
        otsu_threshold, _ = cv2.threshold(column_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        if mode == "strict":
            base_dark = (column_gray < int(otsu_threshold)).astype(np.uint8)
            kernel = np.ones((3, 3), dtype=np.uint8)
            processed = cv2.morphologyEx(base_dark * 255, cv2.MORPH_OPEN, kernel) > 0
        else:
            effective_threshold = int(min(otsu_threshold, 205))
            processed = column_gray < effective_threshold

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(processed.astype(np.uint8), connectivity=8)
        cleaned = np.zeros_like(processed, dtype=np.uint8)
        for label_id in range(1, num_labels):
            width_i = int(stats[label_id, cv2.CC_STAT_WIDTH])
            height_i = int(stats[label_id, cv2.CC_STAT_HEIGHT])
            area = width_i * height_i
            min_area = 4 if mode == "strict" else 2
            if area >= min_area or width_i >= 2 or height_i >= 2:
                cleaned[labels == label_id] = 1
        column_dark = cleaned > 0
        _COLUMN_DARK_CACHE[cache_key] = column_dark

    return column_dark[top:bottom, :]


def largest_true_rectangle(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    if mask.size == 0:
        return None
    height, width = mask.shape
    heights = [0] * width
    best_area = 0
    best_rect: tuple[int, int, int, int] | None = None

    for row in range(height):
        for col in range(width):
            heights[col] = heights[col] + 1 if bool(mask[row, col]) else 0

        stack: list[int] = []
        for idx in range(width + 1):
            curr_height = heights[idx] if idx < width else 0
            while stack and heights[stack[-1]] > curr_height:
                h = heights[stack.pop()]
                if h <= 0:
                    continue
                left = stack[-1] + 1 if stack else 0
                right = idx
                area = h * (right - left)
                if area > best_area:
                    best_area = area
                    best_rect = (row - h + 1, left, row + 1, right)
            stack.append(idx)

    return best_rect


def largest_true_rectangle_touching_right_edge(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    if mask.size == 0:
        return None
    height, width = mask.shape
    suffix_widths = np.zeros(height, dtype=int)
    for row in range(height):
        count = 0
        for col in range(width - 1, -1, -1):
            if not bool(mask[row, col]):
                break
            count += 1
        suffix_widths[row] = count

    best_area = 0
    best_rect: tuple[int, int, int, int] | None = None
    stack: list[int] = []
    for idx in range(height + 1):
        curr_width = int(suffix_widths[idx]) if idx < height else 0
        while stack and suffix_widths[stack[-1]] > curr_width:
            h = int(suffix_widths[stack.pop()])
            if h <= 0:
                continue
            top = stack[-1] + 1 if stack else 0
            bottom = idx
            area = h * (bottom - top)
            if area > best_area:
                best_area = area
                best_rect = (top, width - h, bottom, width)
        stack.append(idx)

    return best_rect


def full_width_blank_run_touching_edge(mask: np.ndarray, edge: str) -> tuple[int, int, int, int] | None:
    if mask.size == 0:
        return None
    if edge not in {"top", "bottom"}:
        raise ValueError(f"unsupported edge: {edge}")

    height, width = mask.shape
    full_blank_rows = np.all(mask, axis=1)
    if edge == "top":
        end = 0
        while end < height and bool(full_blank_rows[end]):
            end += 1
        if end == 0:
            return None
        return (0, 0, end, width)

    start = height - 1
    while start >= 0 and bool(full_blank_rows[start]):
        start -= 1
    if start == height - 1:
        return None
    return (start + 1, 0, height, width)


def find_question_blank_region_from_anchor(
    page_image: Image.Image,
    column: Column,
    anchor_y_min: float,
    column_top: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float]:
    strip_top = max(column_top, anchor_y_min - 8.0)
    strip_bottom = max(strip_top + 0.1, anchor_y_min + 2.0)
    dark = get_clean_dark_crop(
        page_image,
        {
            "x_min": column.x_min,
            "y_min": strip_top,
            "x_max": column.x_max,
            "y_max": strip_bottom,
        },
        scale_x,
        scale_y,
        mode="soft",
    )
    fallback_top = clamp(anchor_y_min - 2.0, column_top, anchor_y_min)
    if dark is None or dark.size == 0:
        return fallback_top, fallback_top

    width = int(dark.shape[1])
    row_counts = dark.sum(axis=1)
    blank_threshold = max(1, int(width * 0.002))
    blank_rows = np.flatnonzero(row_counts <= blank_threshold)
    if blank_rows.size == 0:
        return fallback_top, fallback_top

    run_end = int(blank_rows[-1])
    run_start = run_end
    while run_start - 1 >= 0 and row_counts[run_start - 1] <= blank_threshold:
        run_start -= 1

    blank_top = clamp(strip_top + run_start / scale_y, column_top, anchor_y_min + 2.0)
    blank_bottom = clamp(strip_top + run_end / scale_y, column_top, anchor_y_min + 2.0)
    return blank_top, blank_bottom


def find_question_top_from_anchor(
    page_image: Image.Image,
    column: Column,
    anchor_y_min: float,
    column_top: float,
    scale_x: float,
    scale_y: float,
) -> float:
    _, blank_bottom = find_question_blank_region_from_anchor(
        page_image,
        column,
        anchor_y_min,
        column_top,
        scale_x,
        scale_y,
    )
    return blank_bottom


def compute_column_vertical_bounds(
    column: Column,
    page_lines: Sequence[Line],
    footer_top: float,
    column_anchors: Sequence[Anchor],
) -> tuple[float, float]:
    column_lines = [
        line
        for line in lines_in_rect(page_lines, column.x_min, column.x_max, 0.0, float("inf"))
        if line.text.strip()
    ]
    if not column_lines:
        return 0.0, 0.0

    top = min(line.y_min for line in column_lines)
    bottom = max(line.y_max for line in column_lines)
    return round(top, 2), round(bottom, 2)


def find_anchor_left_blank_rectangle(
    page_image: Image.Image,
    column: Column,
    anchor_min: float,
    footer_top: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float] | None:
    search_right = max(column.x_min + 2.0, anchor_min - 1.0)
    if search_right <= column.x_min + 1.0:
        return None

    bbox = {
        "x_min": round(column.x_min, 2),
        "y_min": 20.0,
        "x_max": round(search_right, 2),
        "y_max": round(footer_top, 2),
    }
    dark = get_clean_dark_crop(page_image, bbox, scale_x, scale_y, mode="soft")
    if dark is None or dark.shape[0] < 20 or dark.shape[1] < 4:
        return None

    blank_mask = ~dark
    rect = largest_true_rectangle(blank_mask)
    if rect is None:
        return None

    top_i, left_i, bottom_i, right_i = rect
    rect_height = bottom_i - top_i
    rect_width = right_i - left_i
    if rect_height < 40 or rect_width < 6:
        return None

    rect_left = clamp(column.x_min + (left_i / scale_x), column.x_min, anchor_min)
    rect_right = clamp(column.x_min + (right_i / scale_x), column.x_min, anchor_min)
    top = clamp(20.0 + (top_i / scale_y), 20.0, footer_top)
    bottom = clamp(20.0 + (bottom_i / scale_y), top + 0.1, footer_top)
    if bottom <= top + 20.0:
        return None
    return round(rect_left, 2), round(top, 2), round(rect_right, 2), round(bottom, 2)


def find_column_right_blank_rectangle(
    page_image: Image.Image,
    column: Column,
    page_lines: Sequence[Line],
    footer_top: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float] | None:
    column_lines = [
        line
        for line in lines_in_rect(page_lines, column.x_min, column.x_max, 20.0, footer_top)
        if line.text.strip()
    ]
    if not column_lines:
        return None

    text_right_edge = max(line.x_max for line in column_lines)
    text_top = min(line.y_min for line in column_lines)
    text_bottom = max(line.y_max for line in column_lines)
    right_band_width = max(90.0, (column.x_max - column.x_min) * 0.25)
    search_left = min(
        column.x_max - 2.0,
        max(column.x_min + 2.0, text_right_edge + 1.0, column.x_max - right_band_width),
    )
    if search_left >= column.x_max - 1.0:
        return None

    bbox = {
        "x_min": round(search_left, 2),
        "y_min": round(max(20.0, text_top - 4.0), 2),
        "x_max": round(column.x_max, 2),
        "y_max": round(min(footer_top, text_bottom + 6.0), 2),
    }
    dark = get_clean_dark_crop(page_image, bbox, scale_x, scale_y, mode="soft")
    if dark is None or dark.shape[0] < 20 or dark.shape[1] < 4:
        return None

    blank_mask = ~dark
    rect = largest_true_rectangle(blank_mask)
    if rect is None:
        return None

    top_i, left_i, bottom_i, right_i = rect
    rect_height = bottom_i - top_i
    rect_width = right_i - left_i
    if rect_height < 40 or rect_width < 6:
        return None

    rect_left = clamp(search_left + (left_i / scale_x), search_left, column.x_max)
    rect_right = clamp(search_left + (right_i / scale_x), search_left, column.x_max)
    top = clamp(20.0 + (top_i / scale_y), 20.0, footer_top)
    bottom = clamp(20.0 + (bottom_i / scale_y), top + 0.1, footer_top)
    if bottom <= top + 20.0:
        return None
    return round(rect_left, 2), round(top, 2), round(rect_right, 2), round(bottom, 2)


def find_column_left_blank_rectangle(
    page_image: Image.Image,
    column: Column,
    page_lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float] | None:
    column_lines = [
        line
        for line in lines_in_rect(
            page_lines,
            column.x_min,
            column.x_max,
            0.0,
            page_image.height / scale_y,
        )
        if line.text.strip()
    ]
    if not column_lines:
        return None

    text_left_edge = min(line.x_min for line in column_lines)
    page_height = page_image.height / scale_y
    search_left = text_left_edge - 16.0
    search_right = text_left_edge - 1.0
    if search_right <= search_left + 1.0:
        return None

    bbox = {
        "x_min": round(search_left, 2),
        "y_min": 0.0,
        "x_max": round(search_right, 2),
        "y_max": round(page_height, 2),
    }
    dark = get_clean_dark_crop(page_image, bbox, scale_x, scale_y, mode="soft")
    if dark is None or dark.shape[0] < 20 or dark.shape[1] < 4:
        return None

    blank_mask = ~dark
    rect = largest_true_rectangle(blank_mask)
    if rect is None:
        return None

    top_i, left_i, bottom_i, right_i = rect
    rect_height = bottom_i - top_i
    rect_width = right_i - left_i
    if rect_height < 40 or rect_width < 6:
        return None

    rect_left = clamp(search_left + (left_i / scale_x), search_left, search_right)
    rect_right = clamp(search_left + (right_i / scale_x), search_left, search_right)
    top = clamp(top_i / scale_y, 0.0, page_height)
    bottom = clamp(bottom_i / scale_y, top + 0.1, page_height)
    if bottom <= top + 20.0:
        return None
    return round(rect_left, 2), round(top, 2), round(rect_right, 2), round(bottom, 2)


def find_blank_rectangle_in_strip(
    page_image: Image.Image,
    search_left: float,
    search_right: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float] | None:
    page_width = page_image.width / scale_x
    page_height = page_image.height / scale_y
    search_left = max(0.0, min(search_left, page_width))
    search_right = max(0.0, min(search_right, page_width))
    if search_right <= search_left + 1.0:
        return None

    bbox = {
        "x_min": round(search_left, 2),
        "y_min": 0.0,
        "x_max": round(search_right, 2),
        "y_max": round(page_height, 2),
    }
    dark = get_clean_dark_crop(page_image, bbox, scale_x, scale_y, mode="soft")
    if dark is None or dark.shape[0] < 20 or dark.shape[1] < 4:
        return None

    blank_mask = ~dark
    rect = largest_true_rectangle(blank_mask)
    if rect is None:
        return None

    top_i, left_i, bottom_i, right_i = rect
    rect_height = bottom_i - top_i
    rect_width = right_i - left_i
    if rect_height < 40 or rect_width < 6:
        return None

    rect_left = clamp(search_left + (left_i / scale_x), search_left, search_right)
    rect_right = clamp(search_left + (right_i / scale_x), search_left, search_right)
    top = clamp(top_i / scale_y, 0.0, page_height)
    bottom = clamp(bottom_i / scale_y, top + 0.1, page_height)
    if bottom <= top + 20.0:
        return None
    return round(rect_left, 2), round(top, 2), round(rect_right, 2), round(bottom, 2)


def compute_effective_columns_and_vertical_bounds(
    columns: Sequence[Column],
    page_image: Image.Image,
    page_lines: Sequence[Line],
    footer_top: float,
    anchors_by_column: dict[int, list[Anchor]],
    scale_x: float,
    scale_y: float,
) -> tuple[dict[int, Column], dict[int, tuple[float, float]]]:
    effective_columns: dict[int, Column] = {}
    vertical_bounds: dict[int, tuple[float, float]] = {}
    text_vertical_bounds: dict[int, tuple[float, float]] = {}
    left_blank_rects: dict[int, tuple[float, float, float, float] | None] = {}
    right_blank_rects: dict[int, tuple[float, float, float, float] | None] = {}
    column_text_bounds: dict[int, tuple[float, float]] = {}
    page_height = page_image.height / scale_y

    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min)
        column_lines = [
            line
            for line in lines_in_rect(page_lines, column.x_min, column.x_max, 0.0, page_height)
            if line.text.strip()
        ]
        text_xmin, text_xmax = compute_column_text_bounds(column, column_anchors, column_lines)
        column_text_bounds[column.index] = (text_xmin, text_xmax)
        text_vertical_bounds[column.index] = compute_column_vertical_bounds(
            column,
            page_lines,
            footer_top,
            column_anchors,
        )

    for idx, column in enumerate(columns):
        text_xmin, text_xmax = column_text_bounds[column.index]
        if idx == 0:
            prev_text_xmax = text_xmin - 24.0
        else:
            prev_text_xmax = column_text_bounds[columns[idx - 1].index][1]
        left_blank_rects[column.index] = find_blank_rectangle_in_strip(
            page_image,
            prev_text_xmax,
            text_xmin,
            scale_x,
            scale_y,
        )
        next_text_xmin = (
            column_text_bounds[columns[idx + 1].index][0]
            if idx < len(columns) - 1
            else text_xmax + 24.0
        )
        right_blank_rects[column.index] = find_blank_rectangle_in_strip(
            page_image,
            text_xmax,
            next_text_xmin,
            scale_x,
            scale_y,
        )

    for idx, column in enumerate(columns):
        rect_left = left_blank_rects.get(column.index)
        rect_right = right_blank_rects.get(column.index)
        top, bottom = text_vertical_bounds[column.index]

        left = column.x_min
        right = column.x_max
        tops = []
        bottoms = []
        if rect_left is not None:
            _, left_top, _, left_bottom = rect_left
            tops.append(left_top)
            bottoms.append(left_bottom)
            left = rect_left[2]
        if rect_right is not None:
            _, right_top, _, right_bottom = rect_right
            tops.append(right_top)
            bottoms.append(right_bottom)
            right = rect_right[0]
        if tops:
            top = max(tops)
        if bottoms:
            bottom = min(bottoms)
        if not tops and not bottoms:
            top, bottom = text_vertical_bounds[column.index]

        effective_columns[column.index] = Column(
            index=column.index,
            x_min=round(left, 2),
            x_max=round(right, 2),
            start_x=column.start_x,
        )
        vertical_bounds[column.index] = (round(top, 2), round(bottom, 2))

    return effective_columns, vertical_bounds


def render_page_image(pdf_path: Path, page_no: int, out_dir: Path, dpi: int) -> Path:
    output_base = out_dir / f"page_{page_no:03d}"
    run_cmd(
        [
            "pdftoppm",
            "-singlefile",
            "-f",
            str(page_no),
            "-l",
            str(page_no),
            "-r",
            str(dpi),
            "-png",
            str(pdf_path),
            str(output_base),
        ],
        capture=False,
    )
    return output_base.with_suffix(".png")
