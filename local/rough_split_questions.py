#!/usr/bin/env python3
"""
按题号对试卷 PDF 做粗切，输出每题图片和元数据。

设计目标：
- 默认依赖尽量少，只使用系统命令 `pdfinfo` / `pdftotext` / `pdftoppm`。
- 先做“按列 + 按题号”的稳定粗切，优先保留题干、选项和配图。
- 不追求一步到位的精确切题，输出结果保留足够信息方便后续人工复核或 LLM 精修。

band 规则总览：
- 结构拆分：
  - 用 Surya 行框合并出文字行。
  - 文字行之间切出初始 `text band / gap band`。
  - 相邻 band 先算 `up/down` 连通性。
  - 对 `up=1 && down=1` 的 gap，用“遮字后连通域在 y 轴上的投影”做结构级二次切分。
- 题目上下沿：
  - 对每个题号锚点，取 `anchor.y_min - 8` 到 `anchor.y_min + 2` 的整栏 `soft` 二值图条带。
  - 找这条条带里最下面的连续空白区。
  - 当前题 `top` 取这段空白区的 `bottom`。
  - 上一题 `bottom` 取下一题空白区的 `top - 0.6`。
- band 判定：
  - `text band` 只分 `table / label / body`。
  - `gap band` 只分 `empty_gap / line_gap / table_gap / visual_gap`。
  - `text band` 先判 `table`，再判 `label`，最后直接 `body` 兜底。
  - `gap band` 先判 `table_gap`，再判 `line_gap`，再判 `empty_gap`，其余归 `visual_gap`。
  - `line_gap` 当前允许多个连通区域；只要每个有效连通区域都满足“细水平线且贴近 band 上边”，就判为 `line_gap`。
  - `text band` 分类后、merge 前，会做一次 `body修正`：
    - 记录 `body_left_candidate = min(最左文字, 最左连通区域)`。
    - 记录 `body_left_tolerance = max(18, 2 * band_height)`。
    - 自上而下扫描 `body` band；若新的 `body_left_candidate` 偏离当前正文流太远，则把该 `body` 改成 `label`。
- band 合并：
  - “围绕core收敛spacer”是核心操作：
    - `core = {body, table, visual_gap}`
    - `spacer = {empty_gap, line_gap, table_gap, label}`
  - 每轮收敛先合并相邻同类 band，再按 core/spacer 规则递归合并直到稳定。
  - 在第一次稳定后，依次处理残留 `table_gap`、`line_gap`、连续 spacer 中的 `label`，
    每一步后都再做一次“围绕core收敛spacer”。
  - 最后把残留 `empty_gap/label` 并入相邻 `table/visual_gap`，再做一次收敛。
  - 目标是最终只留下 `body / table / visual_gap` 三类 merged band。

当前 TODO：
- `q01` 仍有边界/分类问题，后续需要单独回归并补规则。
- `q18` 仍有边界/分类问题，后续需要单独回归并补规则。
"""

from __future__ import annotations

import argparse
import cv2
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw

_COLUMN_DARK_CACHE: dict[tuple[int, int, int, str], np.ndarray] = {}


QUESTION_RE = re.compile(r"^\s*(\d{1,2})\s*[.．、](?!\d)")
QUESTION_PREFIX_RE = re.compile(r"^(\s*)\d{1,2}(\s*[.．、])")
OPTION_RE = re.compile(r"^\s*[A-DＡ-Ｄ]\s*[.．、]")
STRUCTURE_BREAK_RE = re.compile(
    r"^\s*(?:"
    r"[A-Za-zＡ-Ｚａ-ｚ]\s*[.．、\)]"
    r"|[（(]?\d{1,2}\s*[)）.．、]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]"
    r"|[@＠]"
    r")"
)
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+、")
INCOMPLETE_END_RE = re.compile(r"[:：;；,，、=＝\(\[【]\s*$")


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


def parse_surya_line(raw: dict, scale_x: float, scale_y: float) -> Line | None:
    text = (raw.get("text") or "").strip()
    bbox = raw.get("bbox") or []
    confidence = raw.get("confidence", 1.0)
    if not text or len(bbox) != 4:
        return None
    if confidence is not None and confidence < 0.35:
        return None

    x_min, y_min, x_max, y_max = bbox
    if x_max <= x_min or y_max <= y_min:
        return None

    return Line(
        text=text,
        x_min=round(x_min * scale_x, 2),
        y_min=round(y_min * scale_y, 2),
        x_max=round(x_max * scale_x, 2),
        y_max=round(y_max * scale_y, 2),
    )


def overlap_length(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return max(0.0, min(a_max, b_max) - max(a_min, b_min))


def assign_pdf_text_to_detected_box(pdf_lines: Sequence[Line], bbox: tuple[float, float, float, float]) -> str:
    x_min, y_min, x_max, y_max = bbox
    candidates = lines_in_rect(pdf_lines, x_min - 8.0, x_max + 8.0, y_min - 6.0, y_max + 6.0)
    scored: list[tuple[float, Line]] = []
    for line in candidates:
        x_overlap = overlap_length(x_min, x_max, line.x_min, line.x_max)
        y_overlap = overlap_length(y_min, y_max, line.y_min, line.y_max)
        if x_overlap <= 0 or y_overlap <= 0:
            continue
        line_width = max(1.0, line.x_max - line.x_min)
        line_height = max(1.0, line.y_max - line.y_min)
        det_width = max(1.0, x_max - x_min)
        det_height = max(1.0, y_max - y_min)
        x_ratio = x_overlap / min(line_width, det_width)
        y_ratio = y_overlap / min(line_height, det_height)
        score = (x_ratio * 0.4) + (y_ratio * 0.6)
        if y_ratio >= 0.4 and x_ratio >= 0.15:
            scored.append((score, line))

    if not scored:
        return ""

    unique_lines: list[Line] = []
    seen = set()
    for _, line in sorted(scored, key=lambda item: (item[1].y_min, item[1].x_min, -item[0])):
        key = (line.text, line.x_min, line.y_min, line.x_max, line.y_max)
        if key in seen:
            continue
        seen.add(key)
        unique_lines.append(line)
    return " ".join(line.text for line in unique_lines).strip()


def load_surya_lines(
    image_map: dict[int, Path],
    layouts: dict[int, PageLayout],
) -> dict[int, list[Line]]:
    if not image_map:
        return {}

    os.environ["TORCH_DEVICE"] = "mps"
    from surya.detection import DetectionPredictor

    ordered_pages = sorted(image_map)
    images = [Image.open(image_map[page_no]).convert("RGB") for page_no in ordered_pages]
    predictor = DetectionPredictor()
    results = predictor(images)

    page_lines: dict[int, list[Line]] = {}
    for page_no, image, result in zip(ordered_pages, images, results):
        layout = layouts[page_no]
        scale_x = layout.page_width / image.width
        scale_y = layout.page_height / image.height
        detected_lines: list[Line] = []
        for detected_box in result.bboxes:
            px_x_min, px_y_min, px_x_max, px_y_max = detected_box.bbox
            if px_x_max <= px_x_min or px_y_max <= px_y_min:
                continue
            bbox = (
                round(px_x_min * scale_x, 2),
                round(px_y_min * scale_y, 2),
                round(px_x_max * scale_x, 2),
                round(px_y_max * scale_y, 2),
            )
            text = assign_pdf_text_to_detected_box(layout.lines, bbox)
            detected_lines.append(
                Line(
                    text=text,
                    x_min=bbox[0],
                    y_min=bbox[1],
                    x_max=bbox[2],
                    y_max=bbox[3],
                )
            )
        page_lines[page_no] = sorted(detected_lines, key=lambda line: (line.y_min, line.x_min))
    return page_lines


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
    footer_lines = [
        line
        for line in lines
        if line.y_min >= page_height * 0.94
    ]
    if footer_lines:
        return max(page_height * 0.86, min(line.y_min for line in footer_lines) - 10.0)
    return page_height - 24.0


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


def component_box_area(comp: dict[str, int | float]) -> int:
    return int(comp["width"]) * int(comp["height"])


def stats_box_area(stats: np.ndarray, label_id: int) -> int:
    return int(stats[label_id, cv2.CC_STAT_WIDTH]) * int(stats[label_id, cv2.CC_STAT_HEIGHT])


def lines_in_rect(lines: Iterable[Line], x_min: float, x_max: float, y_min: float, y_max: float) -> list[Line]:
    return [
        line
        for line in lines
        if line.x_max >= x_min and line.x_min <= x_max and line.y_max >= y_min and line.y_min <= y_max
    ]


def has_section_title(lines: Sequence[Line]) -> bool:
    return any(SECTION_RE.match(line.text) for line in lines)


def text_looks_incomplete(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).strip()
    if not compact:
        return False
    if INCOMPLETE_END_RE.search(compact):
        return True
    if compact.endswith(("()", "（）")):
        return True
    return compact.endswith(("cm", "N", "kg", "m/kg", "图像", "如下", "如表"))


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


def split_groups_on_question_anchors(groups: Sequence[Sequence[Line]]) -> list[list[Line]]:
    split_groups: list[list[Line]] = []
    for group in groups:
        current: list[Line] = []
        for line in group:
            if QUESTION_RE.match(line.text) and current:
                split_groups.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            split_groups.append(current)
    return split_groups


def split_groups_on_layout_shift(groups: Sequence[Sequence[Line]], column: Column) -> list[list[Line]]:
    column_width = max(1.0, column.x_max - column.x_min)
    split_groups: list[list[Line]] = []
    for group in groups:
        current: list[Line] = [group[0]]
        for prev, line in zip(group, group[1:]):
            prev_width_ratio = (prev.x_max - prev.x_min) / column_width
            line_width_ratio = (line.x_max - line.x_min) / column_width
            prev_left_ratio = (prev.x_min - column.x_min) / column_width
            line_left_ratio = (line.x_min - column.x_min) / column_width
            line_gap = line.y_min - prev.y_max

            shifted_to_full_text = (
                prev_width_ratio < 0.35
                and line_width_ratio > 0.45
                and prev_left_ratio > 0.15
                and line_left_ratio < 0.18
                and line_gap >= 6.0
            )
            if shifted_to_full_text:
                split_groups.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            split_groups.append(current)
    return split_groups


def split_groups_on_structure_lines(groups: Sequence[Sequence[Line]]) -> list[list[Line]]:
    split_groups: list[list[Line]] = []
    for group in groups:
        current: list[Line] = []
        saw_non_option = False
        for line in group:
            is_structure_break = STRUCTURE_BREAK_RE.match(line.text) is not None
            if is_structure_break and current and saw_non_option:
                split_groups.append(current)
                current = [line]
            else:
                current.append(line)
            if not is_structure_break:
                saw_non_option = True
        if current:
            split_groups.append(current)
    return split_groups


def bbox_to_px(bbox: dict[str, float], scale_x: float, scale_y: float) -> tuple[int, int, int, int]:
    left = int(bbox["x_min"] * scale_x)
    top = int(bbox["y_min"] * scale_y)
    right = int(bbox["x_max"] * scale_x)
    bottom = int(bbox["y_max"] * scale_y)
    return left, top, right, bottom


def line_height(line: Line) -> float:
    return max(0.0, line.y_max - line.y_min)


def find_suspicious_ocr_lines(lines: Sequence[Line]) -> set[Line]:
    if not lines:
        return set()

    heights = sorted(line_height(line) for line in lines)
    median_height = heights[len(heights) // 2]
    suspects: set[Line] = set()
    for line in lines:
        compact = re.sub(r"\s+", "", line.text)
        height = line_height(line)
        if height >= max(22.0, median_height * 2.0) and len(compact) <= 6:
            suspects.add(line)
    return suspects


def find_visual_hint_lines(lines: Sequence[Line], column: Column) -> set[Line]:
    hints = set(find_suspicious_ocr_lines(lines))
    column_width = max(1.0, column.x_max - column.x_min)
    column_center = (column.x_min + column.x_max) / 2.0
    for line in lines:
        compact = re.sub(r"\s+", "", line.text)
        width_ratio = (line.x_max - line.x_min) / column_width
        center_offset = abs(((line.x_min + line.x_max) / 2.0) - column_center) / column_width
        if (
            len(compact) <= 4
            and width_ratio <= 0.28
            and center_offset <= 0.18
            and STRUCTURE_BREAK_RE.match(line.text) is None
        ):
            hints.add(line)
    return hints


def build_text_mask(
    shape: tuple[int, int],
    bbox: dict[str, float],
    lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
    ignored_lines: set[Line] | None = None,
) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    ignored = ignored_lines or set()
    for line in lines:
        if line in ignored:
            continue
        line_left = max(0, int((line.x_min - bbox["x_min"]) * scale_x) - 4)
        line_top = max(0, int((line.y_min - bbox["y_min"]) * scale_y) - 3)
        line_right = min(mask.shape[1], int((line.x_max - bbox["x_min"]) * scale_x) + 4)
        line_bottom = min(mask.shape[0], int((line.y_max - bbox["y_min"]) * scale_y) + 3)
        if line_right > line_left and line_bottom > line_top:
            mask[line_top:line_bottom, line_left:line_right] = True
    return mask


def detect_non_text_bands(
    page_image: Image.Image,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
) -> list[tuple[float, float]]:
    if y_max - y_min < 12.0:
        return []

    left, top, right, bottom = bbox_to_px(
        {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max},
        scale_x,
        scale_y,
    )
    if right - left < 10 or bottom - top < 10:
        return []

    crop = page_image.crop((left, top, right, bottom)).convert("L")
    data = np.asarray(crop)
    dark_rows = (data < 235).sum(axis=1)
    min_dark_pixels = max(12, int(data.shape[1] * 0.015))
    active = dark_rows >= min_dark_pixels
    if not active.any():
        return []

    runs: list[tuple[int, int]] = []
    start = None
    for idx, value in enumerate(active):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            if idx - start >= 10:
                runs.append((start, idx))
            start = None
    if start is not None and len(active) - start >= 10:
        runs.append((start, len(active)))

    bands: list[tuple[float, float]] = []
    for run_start, run_end in runs:
        band_y_min = y_min + (run_start / scale_y)
        band_y_max = y_min + (run_end / scale_y)
        bands.append((band_y_min, band_y_max))
    return bands


def detect_embedded_non_text_bands(
    page_image: Image.Image,
    column: Column,
    lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
) -> list[tuple[float, float]]:
    if not lines:
        return []

    bbox = {
        "x_min": column.x_min,
        "y_min": min(line.y_min for line in lines),
        "x_max": column.x_max,
        "y_max": max(line.y_max for line in lines),
    }
    left, top, right, bottom = bbox_to_px(bbox, scale_x, scale_y)
    if right - left < 10 or bottom - top < 10:
        return []

    crop = page_image.crop((left, top, right, bottom)).convert("L")
    data = np.asarray(crop)
    visual_hint_lines = find_visual_hint_lines(lines, column)
    mask = build_text_mask(data.shape, bbox, lines, scale_x, scale_y, visual_hint_lines)
    residual = (data < 248) & ~mask
    row_counts = residual.sum(axis=1)
    min_dark_pixels = max(12, int(residual.shape[1] * 0.04))
    active = row_counts >= min_dark_pixels
    if not active.any():
        return []

    runs: list[tuple[int, int]] = []
    start = None
    for idx, value in enumerate(active):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            if idx - start >= 8:
                runs.append((start, idx))
            start = None
    if start is not None and len(active) - start >= 8:
        runs.append((start, len(active)))

    bands: list[tuple[float, float]] = []
    for run_start, run_end in runs:
        run_height = run_end - run_start
        band_area = int(residual[run_start:run_end].sum())
        min_band_area = max(220, int(residual.shape[1] * run_height * 0.025))
        if band_area < min_band_area:
            continue
        band_y_min = bbox["y_min"] + (run_start / scale_y)
        band_y_max = bbox["y_min"] + (run_end / scale_y)
        bands.append((band_y_min, band_y_max))
    return bands


def split_region_by_row_kind(
    page_image: Image.Image,
    column: Column,
    lines: Sequence[Line],
    scan_lines: Sequence[Line],
    bbox: dict[str, float],
    scale_x: float,
    scale_y: float,
) -> list[tuple[str, float, float]]:
    if bbox["y_max"] - bbox["y_min"] < 6.0:
        return []

    region_lines = list(scan_lines) or list(lines)
    option_lines = [line for line in region_lines if OPTION_RE.match(line.text)]
    if option_lines:
        return [("body_text", bbox["y_min"], bbox["y_max"])]

    visual_hint_lines = find_visual_hint_lines(region_lines, column)
    left, top, right, bottom = bbox_to_px(bbox, scale_x, scale_y)
    if right - left < 10 or bottom - top < 10:
        return [("text", bbox["y_min"], bbox["y_max"])]

    crop = page_image.crop((left, top, right, bottom)).convert("L")
    data = np.asarray(crop)
    body_lines = [line for line in region_lines if line not in visual_hint_lines]
    body_mask = build_text_mask(data.shape, bbox, body_lines, scale_x, scale_y)
    label_mask = build_text_mask(data.shape, bbox, list(visual_hint_lines), scale_x, scale_y)
    text_mask = body_mask | label_mask
    residual = (data < 245) & ~text_mask

    body_counts = body_mask.sum(axis=1)
    label_counts = label_mask.sum(axis=1)
    text_counts = text_mask.sum(axis=1)
    residual_counts = residual.sum(axis=1)
    width = max(1, residual.shape[1])
    body_threshold = max(18, int(width * 0.03))
    label_threshold = max(8, int(width * 0.012))
    residual_threshold = max(8, int(width * 0.012))

    row_kinds: list[str | None] = []
    for body_count, label_count, text_count, residual_count in zip(body_counts, label_counts, text_counts, residual_counts):
        if residual_count <= max(2, int(width * 0.0025)):
            if body_count >= label_threshold:
                row_kinds.append("body_text")
            elif label_count >= label_threshold:
                row_kinds.append("label_text")
            else:
                row_kinds.append(None)
        elif residual_count >= residual_threshold and (
            residual_count >= max(body_count * 0.18, label_count * 0.45) or text_count < body_threshold
        ):
            row_kinds.append("non_text")
        elif body_count >= body_threshold and residual_count < max(10, int(width * 0.02)):
            row_kinds.append("body_text")
        elif label_count >= label_threshold:
            row_kinds.append("label_text")
        elif text_count >= body_threshold and residual_count < max(12, int(width * 0.025)):
            row_kinds.append("body_text")
        else:
            row_kinds.append(None)

    # Fill short unknown gaps so one visual band is not split into many fragments.
    max_gap = max(4, int(scale_y * 2.0))
    idx = 0
    while idx < len(row_kinds):
        if row_kinds[idx] is not None:
            idx += 1
            continue
        gap_start = idx
        while idx < len(row_kinds) and row_kinds[idx] is None:
            idx += 1
        gap_end = idx
        prev_kind = row_kinds[gap_start - 1] if gap_start > 0 else None
        next_kind = row_kinds[gap_end] if gap_end < len(row_kinds) else None
        gap_len = gap_end - gap_start
        if prev_kind is not None and prev_kind == next_kind and gap_len <= max_gap:
            for fill_idx in range(gap_start, gap_end):
                row_kinds[fill_idx] = prev_kind

    segments: list[tuple[str, int, int]] = []
    current_kind: str | None = None
    current_start = 0
    for idx, kind in enumerate(row_kinds):
        if kind is None:
            continue
        if current_kind is None:
            current_kind = kind
            current_start = idx
            continue
        if kind != current_kind:
            segments.append((current_kind, current_start, idx))
            current_kind = kind
            current_start = idx
    if current_kind is not None:
        segments.append((current_kind, current_start, len(row_kinds)))

    if not segments:
        return [("body_text", bbox["y_min"], bbox["y_max"])]

    # Expand segment boundaries to cover adjacent blank rows.
    expanded: list[tuple[str, int, int]] = []
    for seg_index, (kind, start, end) in enumerate(segments):
        prev_end = expanded[-1][2] if expanded else 0
        next_start = segments[seg_index + 1][1] if seg_index + 1 < len(segments) else len(row_kinds)
        pad_top = start - prev_end
        pad_bottom = next_start - end
        expanded_start = start - pad_top // 2
        expanded_end = end + (pad_bottom - pad_bottom // 2)
        expanded.append((kind, expanded_start, expanded_end))

    # Merge tiny runs back into neighbors.
    min_rows_by_kind = {
        "body_text": max(6, int(scale_y * 2.5)),
        "mixed": max(6, int(scale_y * 2.0)),
        "label_text": max(4, int(scale_y * 1.5)),
        "non_text": max(8, int(scale_y * 3.0)),
    }
    merged: list[tuple[str, int, int]] = []
    for kind, start, end in expanded:
        min_rows = min_rows_by_kind.get(kind, max(6, int(scale_y * 2.0)))
        if merged and end - start < min_rows and merged[-1][0] == kind:
            prev_kind, prev_start, prev_end = merged[-1]
            merged[-1] = (prev_kind, prev_start, end)
            continue
        if end - start < min_rows:
            if merged:
                prev_kind, prev_start, prev_end = merged[-1]
                merged[-1] = (prev_kind, prev_start, end)
            else:
                merged.append((kind, start, end))
            continue
        if merged and merged[-1][0] == kind:
            prev_kind, prev_start, prev_end = merged[-1]
            merged[-1] = (prev_kind, prev_start, end)
        else:
            merged.append((kind, start, end))

    bands: list[tuple[str, float, float]] = []
    for kind, start, end in merged:
        if end - start < 4:
            continue
        band_y_min = bbox["y_min"] + (start / scale_y)
        band_y_max = bbox["y_min"] + (end / scale_y)
        if band_y_max - band_y_min < 4.0:
            continue
        bands.append((kind, band_y_min, band_y_max))
    if bands:
        return bands

    # Fallback: if a text block ends with a cluster of visual-hint lines,
    # force a text/image split at that transition.
    if len(visual_hint_lines) >= 2:
        hint_top = min(line.y_min for line in visual_hint_lines)
        normal_lines = [
            line for line in region_lines if line not in visual_hint_lines and line.y_max <= hint_top + 2.0
        ]
        if normal_lines:
            last_normal_bottom = max(line.y_max for line in normal_lines)
            split_y = max(last_normal_bottom + 2.0, hint_top - 12.0)
            if split_y - bbox["y_min"] >= 16.0 and bbox["y_max"] - split_y >= 16.0:
                return [("body_text", bbox["y_min"], split_y), ("non_text", split_y, bbox["y_max"])]

    return [("body_text", bbox["y_min"], bbox["y_max"])]


def build_part_name(page_no: int, question_no: str, index: int) -> str:
    base = f"p{page_no:03d}_q{int(question_no):02d}"
    return f"{base}.png" if index == 1 else f"{base}_{index}.png"


def merge_detected_line_bands(lines: Sequence[Line]) -> list[dict]:
    ordered = sorted(lines, key=lambda line: ((line.y_min + line.y_max) / 2.0, line.x_min))
    merged: list[dict] = []
    for line in ordered:
        if not line.text.strip():
            continue
        line_mid = (line.y_min + line.y_max) / 2.0
        line_height = max(1.0, line.y_max - line.y_min)
        attached = False
        for item in reversed(merged):
            item_mid = (item["y_min"] + item["y_max"]) / 2.0
            vertical_overlap = overlap_length(item["y_min"], item["y_max"], line.y_min, line.y_max)
            if (
                abs(item_mid - line_mid) <= max(8.0, line_height * 0.8)
                or vertical_overlap >= min(line_height, item["y_max"] - item["y_min"]) * 0.35
            ):
                item["lines"].append(line)
                item["x_min"] = min(item["x_min"], line.x_min)
                item["y_min"] = min(item["y_min"], line.y_min)
                item["x_max"] = max(item["x_max"], line.x_max)
                item["y_max"] = max(item["y_max"], line.y_max)
                attached = True
                break
        if not attached:
            merged.append(
                {
                    "lines": [line],
                    "x_min": line.x_min,
                    "y_min": line.y_min,
                    "x_max": line.x_max,
                    "y_max": line.y_max,
                }
            )

    for item in merged:
        item["lines"] = sorted(item["lines"], key=lambda line: line.x_min)
        item["text"] = "    ".join(line.text for line in item["lines"])
    return merged


def expand_line_bands(
    line_bands: Sequence[dict],
    page_top: float,
    page_bottom: float,
    pad_pdf: float,
) -> list[dict]:
    expanded: list[dict] = []
    for idx, band in enumerate(line_bands):
        item = dict(band)
        y_min = max(page_top, item["y_min"] - pad_pdf)
        y_max = min(page_bottom, item["y_max"] + pad_pdf)
        if idx > 0:
            y_min = max(y_min, expanded[-1]["y_max"])
        if idx + 1 < len(line_bands):
            next_band = line_bands[idx + 1]
            max_y = next_band["y_min"] - pad_pdf
            if max_y > y_min:
                y_max = min(y_max, max_y)
        if y_max <= y_min:
            y_max = max(y_min + 0.1, band["y_max"])
        item["y_min"] = y_min
        item["y_max"] = y_max
        expanded.append(item)
    return expanded


def compute_inline_rule_text_extent(
    page_image: Image.Image,
    column: Column,
    line_band: dict,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float]:
    text_x_min = min(line.x_min for line in line_band["lines"])
    text_x_max = max(line.x_max for line in line_band["lines"])

    left, top, right, bottom = bbox_to_px(
        {"x_min": column.x_min, "y_min": line_band["y_min"], "x_max": column.x_max, "y_max": line_band["y_max"]},
        scale_x,
        scale_y,
    )
    if right - left < 10 or bottom - top < 4:
        return text_x_min, text_x_max

    crop = page_image.crop((left, top, right, bottom)).convert("L")
    data = np.asarray(crop)
    # 连通性判定要比普通图文分类更保守，避免浅灰水印/底纹被当成有效连通像素。
    dark = data < 220
    row_counts = dark.sum(axis=1)
    if not row_counts.any():
        return text_x_min, text_x_max

    candidate_rows = [
        idx
        for idx, count in enumerate(row_counts)
        if max(8, int((right - left) * 0.04)) <= count <= max(26, int((right - left) * 0.28))
    ]
    if not candidate_rows:
        return text_x_min, text_x_max

    best_right_px = int(text_x_max * scale_x) - left
    best_left_px = int(text_x_min * scale_x) - left
    for row_idx in candidate_rows:
        dark_cols = np.where(dark[row_idx])[0]
        if len(dark_cols) == 0:
            continue
        runs: list[tuple[int, int]] = []
        run_start = int(dark_cols[0])
        prev = int(dark_cols[0])
        for col_idx in dark_cols[1:]:
            col_idx = int(col_idx)
            if col_idx == prev + 1:
                prev = col_idx
                continue
            runs.append((run_start, prev + 1))
            run_start = col_idx
            prev = col_idx
        runs.append((run_start, prev + 1))
        for run_left, run_right in runs:
            run_width = run_right - run_left
            if run_width < max(20, int((right - left) * 0.08)):
                continue
            rule_left_pdf = column.x_min + (run_left / scale_x)
            rule_right_pdf = column.x_min + (run_right / scale_x)
            # 只把位于文字之间或文字右侧的细横线并入文字覆盖区。
            if rule_right_pdf <= text_x_min + 4.0:
                continue
            if rule_left_pdf > text_x_max + 80.0:
                continue
            best_left_px = min(best_left_px, run_left)
            best_right_px = max(best_right_px, run_right)

    return (
        round(column.x_min + (best_left_px / scale_x), 2),
        round(column.x_min + (best_right_px / scale_x), 2),
    )


def has_visual_content_left_of_text(
    page_image: Image.Image,
    column: Column,
    line_band: dict,
    inline_x_min: float,
    scale_x: float,
    scale_y: float,
) -> bool:
    if inline_x_min - column.x_min < 16.0:
        return False

    dark = get_clean_dark_crop(
        page_image,
        {"x_min": column.x_min, "y_min": line_band["y_min"], "x_max": column.x_max, "y_max": line_band["y_max"]},
        scale_x,
        scale_y,
        pad_y_px=4,
        mode="soft",
    )
    if dark is None or dark.shape[0] < 6 or dark.shape[1] < 12:
        return False

    text_left_px = int((inline_x_min - column.x_min) * scale_x)
    left_limit = min(dark.shape[1], max(0, text_left_px - 4))
    if left_limit < 12:
        return False

    left_dark = dark[:, :left_limit].astype(np.uint8)
    if int(left_dark.sum()) < max(18, int(left_dark.size * 0.01)):
        return False

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(left_dark, connectivity=8)
    for label_id in range(1, num_labels):
        comp_width = int(stats[label_id, cv2.CC_STAT_WIDTH])
        comp_height = int(stats[label_id, cv2.CC_STAT_HEIGHT])
        comp_area = stats_box_area(stats, label_id)
        if comp_area >= 20 and comp_width >= 3 and comp_height >= 3:
            return True
    return False


def detect_table_band_signal(
    components_info: dict[str, object],
    *,
    connect_up: bool = False,
    connect_down: bool = False,
) -> bool:
    masked_dark = components_info.get("masked_dark")
    labels = components_info.get("labels")
    stats = components_info.get("stats")
    components = components_info.get("components") or []
    if (
        masked_dark is None
        or not isinstance(masked_dark, np.ndarray)
        or labels is None
        or stats is None
        or not components
    ):
        return False
    height, width = masked_dark.shape
    if width < 20 or height < 6:
        return False

    def component_touches_vertical_edge(comp: dict[str, int | float], side: str) -> tuple[bool, bool]:
        label_id = int(comp["label"])
        comp_left = int(comp["left"])
        comp_top = int(comp["top"])
        comp_width = int(comp["width"])
        comp_height = int(comp["height"])
        comp_right = comp_left + comp_width
        comp_bottom = comp_top + comp_height
        edge_x = comp_left if side == "left" else comp_right - 1
        if edge_x < 0 or edge_x >= width:
            return False, False
        edge_mask = labels[:, edge_x] == label_id
        edge_count = int(edge_mask.sum())
        if edge_count < max(3, int(comp_height * 0.8)):
            return False, False
        top_touch = comp_top <= 1 and bool(edge_mask[: min(height, 2)].any())
        bottom_touch = comp_bottom >= height - 1 and bool(edge_mask[max(0, height - 2) :].any())
        return top_touch, bottom_touch

    left_component = min(components, key=lambda comp: (int(comp["left"]), -int(comp["height"])))
    right_component = max(
        components,
        key=lambda comp: (int(comp["left"]) + int(comp["width"]), int(comp["height"])),
    )

    left_up, left_down = component_touches_vertical_edge(left_component, "left")
    right_up, right_down = component_touches_vertical_edge(right_component, "right")

    if left_up != right_up or left_down != right_down:
        return False
    if left_up and not connect_up:
        return False
    if left_down and not connect_down:
        return False
    return left_up or left_down


def detect_line_gap_signal(components_info: dict[str, object]) -> bool:
    """
    `line_gap` 识别：
    - 允许存在多个有效连通区域；
    - 但每个区域都必须是贴近上边的细水平线：
      - `height <= 2`
      - `top <= 3`
    """
    masked_dark = components_info.get("masked_dark")
    if masked_dark is None or not isinstance(masked_dark, np.ndarray):
        return False
    band_height, band_width = masked_dark.shape
    if band_height <= 0 or band_width <= 0:
        return False

    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 8 and int(comp["width"]) >= 2 and int(comp["height"]) >= 1
    ]
    if not components:
        return False
    for comp in components:
        comp_top = int(comp["top"])
        comp_height = int(comp["height"])
        if comp_height > 2:
            return False
        # 只认贴着上边的细水平线；上方只允许少量空白。
        if comp_top > 3:
            return False
    return True


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
            # 预处理主要用于压掉浅灰水印/底纹，尽量保留深色细线。
            effective_threshold = int(min(otsu_threshold, 205))
            processed = (column_gray < effective_threshold)

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


def find_question_blank_region_from_anchor(
    page_image: Image.Image,
    column: Column,
    anchor_y_min: float,
    column_top: float,
    scale_x: float,
    scale_y: float,
) -> float:
    """
    在锚点附近条带里找最下面的连续空白区。

    当前条带范围固定为：
    - `anchor.y_min - 8`
    - `anchor.y_min + 2`

    返回 `(blank_top, blank_bottom)`，后续：
    - 当前题 `top` 取 `blank_bottom`
    - 上一题 `bottom` 取下一题的 `blank_top - 0.6`
    """
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


def connected_components_after_text_mask(
    page_image: Image.Image,
    bbox: dict[str, float],
    text_boxes: Sequence[Line],
    scale_x: float,
    scale_y: float,
    *,
    mode: str = "soft",
    pad_y_px: int = 0,
    text_pad_px: int = 1,
) -> dict[str, object]:
    dark = get_clean_dark_crop(
        page_image,
        bbox,
        scale_x,
        scale_y,
        pad_y_px=pad_y_px,
        mode=mode,
    )
    if dark is None:
        return {
            "dark": None,
            "masked_dark": None,
            "num_labels": 0,
            "labels": None,
            "stats": None,
            "centroids": None,
            "components": [],
        }

    masked = dark.astype(np.uint8).copy()
    crop_left, crop_top, crop_right, crop_bottom = bbox_to_px(bbox, scale_x, scale_y)
    crop_top = max(0, crop_top - pad_y_px)
    crop_bottom = min(page_image.height, crop_bottom + pad_y_px)
    crop_width = max(0, crop_right - crop_left)
    crop_height = max(0, crop_bottom - crop_top)
    if crop_width <= 0 or crop_height <= 0:
        return {
            "dark": dark,
            "masked_dark": masked > 0,
            "num_labels": 0,
            "labels": None,
            "stats": None,
            "centroids": None,
            "components": [],
        }

    for line in text_boxes:
        line_left, line_top, line_right, line_bottom = bbox_to_px(
            {
                "x_min": line.x_min,
                "y_min": line.y_min,
                "x_max": line.x_max,
                "y_max": line.y_max,
            },
            scale_x,
            scale_y,
        )
        x0 = max(0, line_left - crop_left - text_pad_px)
        x1 = min(crop_width, line_right - crop_left + text_pad_px)
        y0 = max(0, line_top - crop_top - text_pad_px)
        y1 = min(crop_height, line_bottom - crop_top + text_pad_px)
        if x1 <= x0 or y1 <= y0:
            continue
        masked[y0:y1, x0:x1] = 0

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(masked, connectivity=8)
    components: list[dict[str, int | float]] = []
    for label_id in range(1, num_labels):
        components.append(
            {
                "label": int(label_id),
                "left": int(stats[label_id, cv2.CC_STAT_LEFT]),
                "top": int(stats[label_id, cv2.CC_STAT_TOP]),
                "width": int(stats[label_id, cv2.CC_STAT_WIDTH]),
                "height": int(stats[label_id, cv2.CC_STAT_HEIGHT]),
                "area": int(stats[label_id, cv2.CC_STAT_AREA]),
                "centroid_x": float(centroids[label_id][0]),
                "centroid_y": float(centroids[label_id][1]),
            }
        )

    return {
        "dark": dark,
        "masked_dark": masked > 0,
        "num_labels": int(num_labels),
        "labels": labels,
        "stats": stats,
        "centroids": centroids,
        "components": components,
    }


def has_component_left_of_text(
    components_info: dict[str, object],
    text_left_px: int,
    *,
    min_area: int = 20,
    min_width: int = 3,
    min_height: int = 3,
    margin_px: int = 4,
) -> bool:
    components = components_info.get("components") or []
    left_limit = max(0, text_left_px - margin_px)
    if left_limit < 12:
        return False

    for comp in components:
        comp_left = int(comp["left"])
        comp_right = comp_left + int(comp["width"])
        if comp_right > left_limit:
            continue
        if (
            component_box_area(comp) >= min_area
            and int(comp["width"]) >= min_width
            and int(comp["height"]) >= min_height
        ):
            return True
    return False


def components_left_of_text(
    components_info: dict[str, object],
    text_left_px: int,
    *,
    min_area: int = 20,
    min_width: int = 3,
    min_height: int = 3,
    margin_px: int = 4,
) -> list[dict[str, int | float]]:
    components = components_info.get("components") or []
    left_limit = max(0, text_left_px - margin_px)
    if left_limit < 12:
        return []

    matched: list[dict[str, int | float]] = []
    for comp in components:
        comp_left = int(comp["left"])
        comp_right = comp_left + int(comp["width"])
        if comp_right > left_limit:
            continue
        if (
            component_box_area(comp) >= min_area
            and int(comp["width"]) >= min_width
            and int(comp["height"]) >= min_height
        ):
            matched.append(comp)
    return sorted(matched, key=lambda comp: int(comp["left"]))


def compute_band_connectivity(
    page_image: Image.Image,
    column: Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
) -> tuple[bool, bool]:
    return False, False


def has_spanning_component(
    page_image: Image.Image,
    column: Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
) -> bool:
    dark = get_clean_dark_crop(
        page_image,
        {"x_min": column.x_min, "y_min": y_min, "x_max": column.x_max, "y_max": y_max},
        scale_x,
        scale_y,
    )
    if dark is None or dark.shape[1] < 12 or dark.shape[0] < 6 or not dark.any():
        return False

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8), connectivity=8)
    if num_labels <= 1:
        return False

    top_labels = set(int(v) for v in labels[0, :] if v != 0)
    bottom_labels = set(int(v) for v in labels[-1, :] if v != 0)
    spanning = top_labels & bottom_labels
    if not spanning:
        return False

    min_cols = 6
    min_height = max(3, dark.shape[0] - 1)
    for label_id in spanning:
        width_i = int(stats[label_id, cv2.CC_STAT_WIDTH])
        height_i = int(stats[label_id, cv2.CC_STAT_HEIGHT])
        if width_i >= min_cols or height_i >= min_height:
            return True
    return False


def assign_pairwise_band_connectivity(
    bands: Sequence[dict],
    page_image: Image.Image,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    connected = [dict(band, connect_up=False, connect_down=False) for band in bands]
    if len(connected) < 2:
        return connected

    boundary_pad = max(2.0 / scale_y, 1.2)
    for idx in range(len(connected) - 1):
        upper = connected[idx]
        lower = connected[idx + 1]
        boundary_y = (upper["bbox"]["y_max"] + lower["bbox"]["y_min"]) / 2.0
        window_y_min = max(upper["bbox"]["y_min"], boundary_y - boundary_pad)
        window_y_max = min(lower["bbox"]["y_max"], boundary_y + boundary_pad)
        if window_y_max <= window_y_min:
            continue
        if has_spanning_component(page_image, column, window_y_min, window_y_max, scale_x, scale_y):
            upper["connect_down"] = True
            lower["connect_up"] = True
    return connected


def split_connected_gap_band_on_blank(
    page_image: Image.Image,
    column: Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
    connect_up: bool | None = None,
    connect_down: bool | None = None,
) -> list[tuple[float, float, bool, bool]]:
    if connect_up is None or connect_down is None:
        connect_up, connect_down = compute_band_connectivity(page_image, column, y_min, y_max, scale_x, scale_y)
    if not (connect_up and connect_down):
        return [(y_min, y_max, connect_up, connect_down)]
    parts = find_visual_gap_content_parts(page_image, column, y_min, y_max, scale_x, scale_y)
    if len(parts) < 2:
        return [(y_min, y_max, connect_up, connect_down)]

    top_end = parts[0][1]
    bottom_start = parts[-1][0]
    if top_end <= y_min + 0.5 or bottom_start >= y_max - 0.5 or top_end >= bottom_start - 0.5:
        return [(y_min, y_max, connect_up, connect_down)]

    segments: list[tuple[float, float, bool, bool]] = []
    if top_end > y_min + 0.5:
        segments.append((y_min, top_end, True, False))
    if bottom_start > top_end + 0.5:
        segments.append((top_end, bottom_start, False, False))
    if y_max > bottom_start + 0.5:
        segments.append((bottom_start, y_max, False, True))

    if len(segments) < 2:
        return [(y_min, y_max, connect_up, connect_down)]
    return segments


def find_visual_gap_content_parts(
    page_image: Image.Image,
    column: Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
) -> list[tuple[float, float]]:
    components_info = connected_components_after_text_mask(
        page_image,
        {"x_min": column.x_min, "y_min": y_min, "x_max": column.x_max, "y_max": y_max},
        [],
        scale_x,
        scale_y,
        mode="soft",
    )
    masked_dark = components_info.get("masked_dark")
    if masked_dark is None or not isinstance(masked_dark, np.ndarray):
        return []
    if masked_dark.shape[0] < 4 or masked_dark.shape[1] < 12:
        return []

    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 2 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
    ]
    if not components:
        return []

    intervals = sorted(
        (
            (int(comp["top"]), int(comp["top"]) + int(comp["height"]))
            for comp in components
        ),
        key=lambda item: (item[0], item[1]),
    )
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged:
            merged.append([start, end])
            continue
        last = merged[-1]
        if start <= last[1] + 1:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])

    parts: list[tuple[float, float]] = []
    for start, end in merged:
        part_y_min = y_min + start / scale_y
        part_y_max = y_min + end / scale_y
        if part_y_max > part_y_min:
            parts.append((round(part_y_min, 2), round(part_y_max, 2)))
    return parts


def build_structural_bands(
    line_bands: Sequence[dict],
    page_image: Image.Image,
    column: Column,
    region_y_min: float,
    region_y_max: float,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    """
    结构阶段只负责把题目区域切成稳定 band，不做语义合并。

    当前约定：
    - 先按文字行切出 `text band` 和中间的 `gap band`。
    - 所有 band 先算相邻边界 `up/down`。
    - 对 `up=1 && down=1` 的 gap，再按连通域 y 投影做二次切分，
      可以切出上/中/下多个部分，并重新对齐 `up/down`。
    """
    bands: list[dict] = []
    previous_y = region_y_min
    band_index = 1

    for line_band in line_bands:
        if line_band["y_min"] > previous_y:
            bands.append(
                {
                    "index": band_index,
                    "band_type": "gap",
                    "text": "",
                    "bbox": {
                        "x_min": round(column.x_min, 2),
                        "y_min": round(previous_y, 2),
                        "x_max": round(column.x_max, 2),
                        "y_max": round(line_band["y_min"], 2),
                    },
                    "connect_up": False,
                    "connect_down": False,
                }
            )
            band_index += 1

        line_x_min = min(line.x_min for line in line_band["lines"])
        line_x_max = max(line.x_max for line in line_band["lines"])
        bands.append(
            {
                "index": band_index,
                "band_type": "text",
                "text": line_band["text"],
                "line_band": line_band,
                "left_ratio": round((line_x_min - column.x_min) / max(1.0, column.x_max - column.x_min), 4),
                "width_ratio": round((line_x_max - line_x_min) / max(1.0, column.x_max - column.x_min), 4),
                "bbox": {
                    "x_min": round(column.x_min, 2),
                    "y_min": round(line_band["y_min"], 2),
                    "x_max": round(column.x_max, 2),
                    "y_max": round(line_band["y_max"], 2),
                },
                "connect_up": False,
                "connect_down": False,
            }
        )
        band_index += 1
        previous_y = line_band["y_max"]

    if previous_y < region_y_max:
        bands.append(
            {
                "index": band_index,
                "band_type": "gap",
                "text": "",
                "bbox": {
                    "x_min": round(column.x_min, 2),
                    "y_min": round(previous_y, 2),
                    "x_max": round(column.x_max, 2),
                    "y_max": round(region_y_max, 2),
                },
                "connect_up": False,
                "connect_down": False,
            }
        )

    bands = assign_pairwise_band_connectivity(bands, page_image, column, scale_x, scale_y)

    split_bands: list[dict] = []
    next_index = 1
    for band in bands:
        if band["band_type"] == "gap" and band.get("connect_up") and band.get("connect_down"):
            for gap_y_min, gap_y_max, connect_up, connect_down in split_connected_gap_band_on_blank(
                page_image,
                column,
                band["bbox"]["y_min"],
                band["bbox"]["y_max"],
                scale_x,
                scale_y,
                connect_up=True,
                connect_down=True,
            ):
                split_bands.append(
                    {
                        "index": next_index,
                        "band_type": "gap",
                        "text": "",
                        "bbox": {
                            "x_min": round(column.x_min, 2),
                            "y_min": round(gap_y_min, 2),
                            "x_max": round(column.x_max, 2),
                            "y_max": round(gap_y_max, 2),
                        },
                        "connect_up": connect_up,
                        "connect_down": connect_down,
                    }
                )
                next_index += 1
            continue

        copied = dict(band)
        copied["index"] = next_index
        split_bands.append(copied)
        next_index += 1

    return assign_pairwise_band_connectivity(split_bands, page_image, column, scale_x, scale_y)


def classify_text_band_in_sequence(
    band: dict,
    prev_band: dict | None,
    page_image: Image.Image,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> dict:
    item = dict(band)
    line_band = item["line_band"]
    lines = line_band["lines"]
    text_x_min = min(line.x_min for line in lines)
    text_area_px = 0
    for line in lines:
        line_left, line_top, line_right, line_bottom = bbox_to_px(
            {
                "x_min": line.x_min,
                "y_min": line.y_min,
                "x_max": line.x_max,
                "y_max": line.y_max,
            },
            scale_x,
            scale_y,
        )
        text_area_px += max(0, line_right - line_left) * max(0, line_bottom - line_top)
    components_info = connected_components_after_text_mask(
        page_image,
        {"x_min": column.x_min, "y_min": line_band["y_min"], "x_max": column.x_max, "y_max": line_band["y_max"]},
        lines,
        scale_x,
        scale_y,
        mode="soft",
        pad_y_px=4,
        text_pad_px=1,
    )
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 6 and int(comp["width"]) >= 2 and int(comp["height"]) >= 2
    ]
    item["semantic_area"] = text_area_px + sum(component_box_area(comp) for comp in components)
    if components:
        component_left = min(column.x_min + int(comp["left"]) / scale_x for comp in components)
        item["body_left_candidate"] = min(text_x_min, component_left)
    else:
        item["body_left_candidate"] = text_x_min
    item["body_left_tolerance"] = max(
        18.0,
        2.0 * max(0.0, float(line_band["y_max"]) - float(line_band["y_min"])),
    )
    kind = classify_text_line_band(
        line_band,
        column,
        page_image,
        scale_x,
        scale_y,
        band_context=band,
        prev_band=prev_band,
    )
    item["kind"] = kind
    return item


def classify_gap_band_in_sequence(
    band: dict,
    prev_band: dict | None,
    page_image: Image.Image,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> dict:
    item = dict(band)
    components_info = connected_components_after_text_mask(
        page_image,
        {"x_min": column.x_min, "y_min": item["bbox"]["y_min"], "x_max": column.x_max, "y_max": item["bbox"]["y_max"]},
        [],
        scale_x,
        scale_y,
        mode="soft",
    )
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 4 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
    ]
    item["semantic_area"] = sum(component_box_area(comp) for comp in components)
    item["kind"] = classify_gap_band_kind(
        page_image,
        column,
        item["bbox"]["y_min"],
        item["bbox"]["y_max"],
        scale_x,
        scale_y,
        band_context=band,
        prev_band=prev_band,
    )
    return item


def classify_bands_in_order(
    structural_bands: Sequence[dict],
    page_image: Image.Image,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    """
    把结构 band 序列转成带 `kind` 的 band 序列。

    当前约定：
    - `text band` 只分 `table / label / body`。
    - `gap band` 只分 `empty_gap / line_gap / table_gap / visual_gap`。
    - 分类是单向序列式的，只依赖当前 band、自身图像特征和前一个已分类 band。
    - 分类完成后、merge 前，会做一次 `body` 修正：
      用自上而下的 `body_left` 对齐线检查可疑 `body`，必要时改成 `label`。
    - `body_left_tolerance` 当前定义为：
      `max(18, 2 * band_height)`，用于容忍正常正文缩进。
    """
    def classify_once(sequence: Sequence[dict]) -> list[dict]:
        classified_once: list[dict] = []

        for band in sequence:
            prev_band = classified_once[-1] if classified_once else None
            if band["band_type"] == "text":
                item = classify_text_band_in_sequence(
                    band,
                    prev_band,
                    page_image,
                    column,
                    scale_x,
                    scale_y,
                )
            else:
                item = classify_gap_band_in_sequence(
                    band,
                    prev_band,
                    page_image,
                    column,
                    scale_x,
                    scale_y,
                )
            classified_once.append(item)

        return classified_once

    def refine_body_adjacent_visual_gaps(classified_once: Sequence[dict]) -> tuple[list[dict], bool]:
        refined: list[dict] = []
        changed = False
        next_index = 1

        for idx, band in enumerate(classified_once):
            prev_kind = classified_once[idx - 1]["kind"] if idx > 0 else None
            next_kind = classified_once[idx + 1]["kind"] if idx + 1 < len(classified_once) else None
            if band["band_type"] != "gap" or band.get("kind") != "visual_gap":
                copied = dict(band)
                copied["index"] = next_index
                refined.append(copied)
                next_index += 1
                continue

            split_top = prev_kind == "body"
            split_bottom = next_kind == "body"
            if not (split_top or split_bottom):
                copied = dict(band)
                copied["index"] = next_index
                refined.append(copied)
                next_index += 1
                continue

            parts = find_visual_gap_content_parts(
                page_image,
                column,
                band["bbox"]["y_min"],
                band["bbox"]["y_max"],
                scale_x,
                scale_y,
            )
            if len(parts) <= 1:
                copied = dict(band)
                copied["index"] = next_index
                refined.append(copied)
                next_index += 1
                continue

            split_points = [band["bbox"]["y_min"]]
            if split_top:
                top_end = parts[0][1]
                if top_end > split_points[-1] + 0.5:
                    split_points.append(top_end)
            if split_bottom and len(parts) >= 2:
                bottom_start = parts[-1][0]
                if bottom_start > split_points[-1] + 0.5 and bottom_start < band["bbox"]["y_max"] - 0.5:
                    split_points.append(bottom_start)
            if band["bbox"]["y_max"] > split_points[-1] + 0.5:
                split_points.append(band["bbox"]["y_max"])

            if len(split_points) <= 2:
                copied = dict(band)
                copied["index"] = next_index
                refined.append(copied)
                next_index += 1
                continue

            changed = True
            for start, end in zip(split_points[:-1], split_points[1:]):
                if end <= start + 0.5:
                    continue
                refined.append(
                    {
                        "index": next_index,
                        "band_type": "gap",
                        "text": "",
                        "bbox": {
                            "x_min": round(column.x_min, 2),
                            "y_min": round(start, 2),
                            "x_max": round(column.x_max, 2),
                            "y_max": round(end, 2),
                        },
                        "connect_up": False,
                        "connect_down": False,
                    }
                )
                next_index += 1

        return refined, changed

    def apply_body_correction(classified_once: Sequence[dict]) -> list[dict]:
        corrected: list[dict] = []
        body_left: float | None = None
        body_tolerance: float | None = None

        for band in classified_once:
            item = dict(band)
            if item.get("kind") != "body":
                corrected.append(item)
                continue

            current_left = item.get("body_left_candidate")
            if not isinstance(current_left, (int, float)):
                corrected.append(item)
                continue

            if body_left is None:
                body_left = float(current_left)
                body_tolerance = float(item.get("body_left_tolerance", 18.0))
                item["body_left"] = body_left
                corrected.append(item)
                continue

            current_tolerance = float(item.get("body_left_tolerance", 18.0))
            align_tolerance = max(18.0, body_tolerance or 18.0, current_tolerance)
            if abs(float(current_left) - body_left) > align_tolerance:
                item["kind"] = "label"
                item.pop("body_left", None)
            else:
                body_left = float(current_left)
                body_tolerance = current_tolerance
                item["body_left"] = body_left
            corrected.append(item)

        return corrected

    classified = classify_once(structural_bands)
    refined_structural, changed = refine_body_adjacent_visual_gaps(classified)
    if not changed:
        return apply_body_correction(classified)

    refined_structural = assign_pairwise_band_connectivity(refined_structural, page_image, column, scale_x, scale_y)
    return apply_body_correction(classify_once(refined_structural))


def has_vertical_rule_near(
    dark: np.ndarray,
    x_center: int,
    min_height_ratio: float = 0.35,
    search_radius: int = 8,
) -> bool:
    height, width = dark.shape
    if width <= 0 or height <= 0:
        return False
    best_active_rows = 0
    for probe in range(max(0, x_center - search_radius), min(width, x_center + search_radius + 1)):
        left = max(0, probe - 2)
        right = min(width, probe + 3)
        if right <= left:
            continue
        column_dark = dark[:, left:right].sum(axis=1)
        active_rows = int((column_dark >= max(1, int((right - left) * 0.6))).sum())
        best_active_rows = max(best_active_rows, active_rows)
    return best_active_rows >= int(height * min_height_ratio)


def has_vertical_rule_in_range(
    dark: np.ndarray,
    x_start: int,
    x_end: int,
    min_height_ratio: float = 0.35,
) -> bool:
    height, width = dark.shape
    if width <= 0 or height <= 0:
        return False
    x_start = max(0, min(x_start, width - 1))
    x_end = max(0, min(x_end, width - 1))
    if x_end < x_start:
        x_start, x_end = x_end, x_start

    best_active_rows = 0
    for probe in range(x_start, x_end + 1):
        column_dark = dark[:, probe]
        active_rows = int(column_dark.sum())
        best_active_rows = max(best_active_rows, active_rows)
    return best_active_rows >= int(height * min_height_ratio)


def looks_like_table_text_row(
    column: Column,
    line_band: dict,
    components_info: dict[str, object],
    scale_x: float,
) -> bool:
    raw_boxes = sorted(line_band["lines"], key=lambda line: line.x_min)
    if not raw_boxes:
        return False

    masked_dark = components_info.get("masked_dark")
    components = components_info.get("components") or []
    if masked_dark is None or not isinstance(masked_dark, np.ndarray):
        return False
    band_height = int(masked_dark.shape[0])
    if band_height < 8:
        return False

    first_left = int((raw_boxes[0].x_min - column.x_min) * scale_x)
    last_right = int((raw_boxes[-1].x_max - column.x_min) * scale_x)

    left_candidates = []
    right_candidates = []
    for comp in components:
        comp_left = int(comp["left"])
        comp_width = int(comp["width"])
        comp_right = comp_left + comp_width
        comp_height = int(comp["height"])
        if comp_right <= first_left:
            left_candidates.append(comp)
        if comp_left >= last_right:
            right_candidates.append(comp)

    if not left_candidates or not right_candidates:
        return False

    left_component = min(left_candidates, key=lambda comp: (int(comp["left"]), -int(comp["height"])))
    right_component = max(right_candidates, key=lambda comp: (int(comp["left"]) + int(comp["width"]), int(comp["height"])))

    min_component_height = max(3, int(band_height * 0.8))
    if int(left_component["height"]) < min_component_height:
        return False
    if int(right_component["height"]) < min_component_height:
        return False
    return True


def classify_text_line_band(
    line_band: dict,
    column: Column,
    page_image: Image.Image,
    scale_x: float,
    scale_y: float,
    band_context: dict | None = None,
    prev_band: dict | None = None,
) -> str:
    """
    `text band` 分类约定：
    1. 先判 `table`
    2. 再判 `label`
    3. 其余直接 `body`

    当前保留的 `label` 信号：
    - `connect_up` 或 `connect_down` 为真，且该行明显不像正文续行
    - 遮字后存在接近 band 高度的贯通连通域
    - 遮字后连通域总面积大于文字区域面积
    - 文字左侧存在多个连通域
    - 文字左侧存在一个连通域
    """
    lines = line_band["lines"]
    components_info = connected_components_after_text_mask(
        page_image,
        {"x_min": column.x_min, "y_min": line_band["y_min"], "x_max": column.x_max, "y_max": line_band["y_max"]},
        lines,
        scale_x,
        scale_y,
        mode="soft",
        pad_y_px=4,
        text_pad_px=1,
    )
    if looks_like_table_text_row(column, line_band, components_info, scale_x):
        return "table"

    text_x_min = min(line.x_min for line in lines)
    text_x_max = max(line.x_max for line in lines)
    text_area_px = 0
    for line in lines:
        line_left, line_top, line_right, line_bottom = bbox_to_px(
            {
                "x_min": line.x_min,
                "y_min": line.y_min,
                "x_max": line.x_max,
                "y_max": line.y_max,
            },
            scale_x,
            scale_y,
        )
        text_area_px += max(0, line_right - line_left) * max(0, line_bottom - line_top)
    masked_dark = components_info.get("masked_dark")
    band_area_px = int(masked_dark.size) if isinstance(masked_dark, np.ndarray) else 0
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 6 and int(comp["width"]) >= 2 and int(comp["height"]) >= 2
    ]
    component_area = sum(component_box_area(comp) for comp in components)
    band_height_px = int(masked_dark.shape[0]) if isinstance(masked_dark, np.ndarray) else 0

    prev_kind = prev_band.get("kind") if prev_band else None

    connect_up = bool(band_context.get("connect_up")) if band_context else False
    connect_down = bool(band_context.get("connect_down")) if band_context else False
    has_spanning_component = any(int(comp["height"]) >= max(3, int(band_height_px * 0.95)) for comp in components)

    column_width = max(1.0, column.x_max - column.x_min)
    body_like_left = ((text_x_min - column.x_min) / column_width) <= 0.18
    body_like_width = ((text_x_max - text_x_min) / column_width) >= 0.3

    if (connect_up or connect_down) and not (body_like_left and body_like_width):
        return "label"
    if has_spanning_component:
        return "label"
    if component_area > max(text_area_px, 0):
        return "label"

    text_left_px = int((text_x_min - column.x_min) * scale_x)
    left_components = components_left_of_text(components_info, text_left_px)
    if len(left_components) >= 2:
        return "label"
    if len(left_components) == 1:
        if prev_kind != "body":
            return "label"
        return "label"
    return "body"


def classify_gap_band_kind(
    image: Image.Image,
    column: Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
    band_context: dict | None = None,
    prev_band: dict | None = None,
) -> str:
    """
    `gap band` 分类约定：
    1. `table_gap`
    2. `line_gap`
    3. `empty_gap`
    4. 其余为 `visual_gap`
    """
    components_info = connected_components_after_text_mask(
        image,
        {"x_min": column.x_min, "y_min": y_min, "x_max": column.x_max, "y_max": y_max},
        [],
        scale_x,
        scale_y,
        mode="soft",
    )
    masked_dark = components_info.get("masked_dark")
    band_area_px = int(masked_dark.size) if isinstance(masked_dark, np.ndarray) else 0
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 4 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
    ]
    component_area = sum(component_box_area(comp) for comp in components)

    if detect_table_band_signal(
        components_info,
        connect_up=bool(band_context.get("connect_up")) if band_context else False,
        connect_down=bool(band_context.get("connect_down")) if band_context else False,
    ):
        return "table_gap"
    if detect_line_gap_signal(components_info):
        return "line_gap"
    if y_max - y_min <= 3.0:
        return "empty_gap"
    if component_area <= max(20, int(band_area_px * 0.002)):
        return "empty_gap"
    return "visual_gap"


def merge_classified_bands(bands: Sequence[dict]) -> list[dict]:
    """
    合并 classified bands，核心操作叫“围绕core收敛spacer”。

    约定：
    - `core = {body, table, visual_gap}`
    - `spacer = {empty_gap, line_gap, table_gap, label}`
    - `line_gap` 在合并前默认设 `connect_up = 1`
    - 每轮“围绕core收敛spacer”都先压平相邻同类，再按 core/spacer 关系递归合并。

    当前完整顺序：
    1. 做一次“围绕core收敛spacer”
    2. 把残留 `table_gap` 改成 `visual_gap`
    3. 再做一次“围绕core收敛spacer”
    4. 把残留 `line_gap` 并到前一个 `empty_gap/label`
    5. 再做一次“围绕core收敛spacer”
    6. 连续 spacer 中只要含 `label`，整段压成一个 `label`
    7. 再做一次“围绕core收敛spacer”
    8. 把残留 `empty_gap/label` 并到相邻 `table/visual_gap`
    9. 再做一次“围绕core收敛spacer”

    目标：
    - 最终 merged band 中不再保留 spacer
    - 只剩 `body / table / visual_gap`
    """
    core_kinds = {"body", "table", "visual_gap"}
    spacer_kinds = {"empty_gap", "line_gap", "table_gap", "label"}

    def boundary_connected(upper: dict, lower: dict) -> bool:
        return bool(upper.get("connect_down") and lower.get("connect_up"))

    def item_member_kinds(item: dict) -> list[str]:
        return list(item.get("member_kinds", [item["kind"]]))

    def item_member_indices(item: dict) -> list[int]:
        return list(item.get("member_indices", [item["index"]]))

    def item_text(item: dict) -> str:
        return item.get("text", "")

    def item_semantic_area(item: dict) -> int:
        return int(item.get("semantic_area", 0))

    def merge_items(group: Sequence[dict], kind: str) -> dict:
        return {
            "kind": kind,
            "index": group[0]["index"],
            "band_type": group[0].get("band_type", "text"),
            "text": "\n".join(part for item in group for part in [item_text(item)] if part),
            "member_indices": [idx for item in group for idx in item_member_indices(item)],
            "member_kinds": [kind for item in group for kind in item_member_kinds(item)],
            "bbox": {
                "x_min": group[0]["bbox"]["x_min"],
                "y_min": min(item["bbox"]["y_min"] for item in group),
                "x_max": group[0]["bbox"]["x_max"],
                "y_max": max(item["bbox"]["y_max"] for item in group),
            },
            "connect_up": group[0].get("connect_up", False),
            "connect_down": group[-1].get("connect_down", False),
            "semantic_area": sum(item_semantic_area(item) for item in group),
        }

    def choose_visual_merge_kind(core_item: dict, spacer_item: dict) -> str:
        if core_item["kind"] != "visual_gap":
            return core_item["kind"]
        return spacer_item["kind"] if item_semantic_area(spacer_item) > item_semantic_area(core_item) else "visual_gap"

    prepared_bands: list[dict] = []
    for band in bands:
        item = dict(band)
        if item.get("kind") == "line_gap":
            item["connect_up"] = True
        prepared_bands.append(item)

    def converge_core_spacer(items: list[dict]) -> list[dict]:
        merged_items = items
        changed = True
        while changed:
            changed = False

            coalesced: list[dict] = []
            idx = 0
            while idx < len(merged_items):
                group = [merged_items[idx]]
                idx += 1
                while idx < len(merged_items) and merged_items[idx]["kind"] == group[-1]["kind"]:
                    group.append(merged_items[idx])
                    idx += 1
                coalesced.append(merge_items(group, group[0]["kind"]))
                if len(group) > 1:
                    changed = True

            next_bands: list[dict] = []
            idx = 0
            while idx < len(coalesced):
                if (
                    idx == 0
                    and idx + 1 < len(coalesced)
                    and coalesced[idx]["kind"] in spacer_kinds
                    and coalesced[idx + 1]["kind"] in core_kinds
                ):
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1]],
                            coalesced[idx + 1]["kind"],
                        )
                    )
                    idx += 2
                    changed = True
                    continue

                if (
                    idx + 2 < len(coalesced)
                    and coalesced[idx]["kind"] in {"body", "table"}
                    and coalesced[idx + 1]["kind"] in spacer_kinds
                    and coalesced[idx + 2]["kind"] == coalesced[idx]["kind"]
                ):
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1], coalesced[idx + 2]],
                            coalesced[idx]["kind"],
                        )
                    )
                    idx += 3
                    changed = True
                    continue

                if (
                    idx + 1 < len(coalesced)
                    and coalesced[idx]["kind"] in core_kinds
                    and coalesced[idx + 1]["kind"] in spacer_kinds
                    and (
                        coalesced[idx + 1].get("connect_up", False)
                        or (
                            coalesced[idx]["kind"] == "table"
                            and coalesced[idx + 1]["kind"] == "table_gap"
                        )
                    )
                ):
                    merged_kind = choose_visual_merge_kind(coalesced[idx], coalesced[idx + 1])
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1]],
                            merged_kind,
                        )
                    )
                    idx += 2
                    changed = True
                    continue

                if (
                    idx + 1 < len(coalesced)
                    and coalesced[idx]["kind"] in spacer_kinds
                    and coalesced[idx + 1]["kind"] in core_kinds
                    and (
                        coalesced[idx].get("connect_down", False)
                        or (
                            coalesced[idx]["kind"] == "table_gap"
                            and coalesced[idx + 1]["kind"] == "table"
                        )
                    )
                ):
                    merged_kind = (
                        choose_visual_merge_kind(coalesced[idx + 1], coalesced[idx])
                        if coalesced[idx + 1]["kind"] == "visual_gap"
                        else coalesced[idx + 1]["kind"]
                    )
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1]],
                            merged_kind,
                        )
                    )
                    idx += 2
                    changed = True
                    continue

                if (
                    idx == len(coalesced) - 2
                    and coalesced[idx]["kind"] in core_kinds
                    and coalesced[idx + 1]["kind"] in spacer_kinds
                ):
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1]],
                            coalesced[idx]["kind"],
                        )
                    )
                    idx += 2
                    changed = True
                    continue

                if (
                    idx + 1 < len(coalesced)
                    and coalesced[idx]["kind"] in core_kinds
                    and coalesced[idx + 1]["kind"] == coalesced[idx]["kind"]
                    and boundary_connected(coalesced[idx], coalesced[idx + 1])
                ):
                    next_bands.append(
                        merge_items(
                            [coalesced[idx], coalesced[idx + 1]],
                            coalesced[idx]["kind"],
                        )
                    )
                    idx += 2
                    changed = True
                    continue

                next_bands.append(coalesced[idx])
                idx += 1
            merged_items = next_bands
        return merged_items

    merged_bands = converge_core_spacer(prepared_bands)

    normalized_bands: list[dict] = []
    table_gap_downgraded = False
    for item in merged_bands:
        if item["kind"] == "table_gap":
            normalized_bands.append(merge_items([item], "visual_gap"))
            table_gap_downgraded = True
        else:
            normalized_bands.append(item)

    if table_gap_downgraded:
        normalized_bands = converge_core_spacer(normalized_bands)

    line_gap_absorbed: list[dict] = []
    idx = 0
    line_gap_changed = False
    absorbable_prev_spacers = {"empty_gap", "label"}
    while idx < len(normalized_bands):
        item = normalized_bands[idx]
        if (
            item["kind"] == "line_gap"
            and line_gap_absorbed
            and line_gap_absorbed[-1]["kind"] in absorbable_prev_spacers
        ):
            prev_item = line_gap_absorbed.pop()
            line_gap_absorbed.append(merge_items([prev_item, item], prev_item["kind"]))
            line_gap_changed = True
            idx += 1
            continue
        line_gap_absorbed.append(item)
        idx += 1

    if line_gap_changed:
        line_gap_absorbed = converge_core_spacer(line_gap_absorbed)

    collapsed_spacers: list[dict] = []
    idx = 0
    spacer_only_kinds = {"empty_gap", "label"}
    spacer_collapsed = False
    while idx < len(line_gap_absorbed):
        if line_gap_absorbed[idx]["kind"] not in spacer_only_kinds:
            collapsed_spacers.append(line_gap_absorbed[idx])
            idx += 1
            continue
        group = [line_gap_absorbed[idx]]
        idx += 1
        while idx < len(line_gap_absorbed) and line_gap_absorbed[idx]["kind"] in spacer_only_kinds:
            group.append(line_gap_absorbed[idx])
            idx += 1
        if len(group) > 1 and any(item["kind"] == "label" for item in group):
            collapsed_spacers.append(merge_items(group, "label"))
            spacer_collapsed = True
        else:
            collapsed_spacers.extend(group)

    if spacer_collapsed:
        collapsed_spacers = converge_core_spacer(collapsed_spacers)

    final_spacer_kinds = {"empty_gap", "label"}
    absorb_target_kinds = {"table", "visual_gap"}
    absorbed_visual_table: list[dict] = []
    idx = 0
    final_absorb_changed = False
    while idx < len(collapsed_spacers):
        item = collapsed_spacers[idx]
        if item["kind"] not in final_spacer_kinds:
            absorbed_visual_table.append(item)
            idx += 1
            continue

        prev_item = absorbed_visual_table[-1] if absorbed_visual_table else None
        next_item = collapsed_spacers[idx + 1] if idx + 1 < len(collapsed_spacers) else None

        if prev_item is not None and prev_item["kind"] in absorb_target_kinds:
            absorbed_visual_table[-1] = merge_items([prev_item, item], prev_item["kind"])
            final_absorb_changed = True
            idx += 1
            continue

        if next_item is not None and next_item["kind"] in absorb_target_kinds:
            absorbed_visual_table.append(merge_items([item, next_item], next_item["kind"]))
            final_absorb_changed = True
            idx += 2
            continue

        absorbed_visual_table.append(item)
        idx += 1

    if final_absorb_changed:
        absorbed_visual_table = converge_core_spacer(absorbed_visual_table)

    return absorbed_visual_table


def refine_stream_with_band_clusters(
    stream_blocks: Sequence[dict],
    page_image: Image.Image,
    column: Column,
    page_scan_lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    if not stream_blocks:
        return []

    stream_bbox = {
        "x_min": min(block["bbox"]["x_min"] for block in stream_blocks),
        "y_min": min(block["bbox"]["y_min"] for block in stream_blocks),
        "x_max": max(block["bbox"]["x_max"] for block in stream_blocks),
        "y_max": max(block["bbox"]["y_max"] for block in stream_blocks),
    }
    region_lines = [
        line
        for line in lines_in_rect(
            page_scan_lines,
            column.x_min,
            column.x_max,
            stream_bbox["y_min"],
            stream_bbox["y_max"],
        )
        if line.text.strip()
    ]
    if len(region_lines) < 2:
        return list(stream_blocks)

    pad_pdf = 2.0 / scale_y
    stream_bbox["y_min"] = min(stream_bbox["y_min"], min(line.y_min for line in region_lines) - pad_pdf)
    stream_bbox["y_max"] = max(stream_bbox["y_max"], max(line.y_max for line in region_lines) + pad_pdf)

    line_bands = expand_line_bands(
        merge_detected_line_bands(region_lines),
        stream_bbox["y_min"],
        stream_bbox["y_max"],
        pad_pdf,
    )
    if len(line_bands) < 2:
        return list(stream_blocks)

    bands = build_structural_bands(
        line_bands,
        page_image,
        column,
        stream_bbox["y_min"],
        stream_bbox["y_max"],
        scale_x,
        scale_y,
    )
    bands = classify_bands_in_order(bands, page_image, column, scale_x, scale_y)
    merged_bands = merge_classified_bands(bands)
    if not merged_bands:
        return list(stream_blocks)

    refined: list[dict] = []
    for idx, band in enumerate(merged_bands):
        y_min = band["bbox"]["y_min"]
        y_max = band["bbox"]["y_max"]
        if idx == 0:
            y_min = stream_bbox["y_min"]
        if idx == len(merged_bands) - 1:
            y_max = stream_bbox["y_max"]
        refined.append(
            {
                "kind": (
                    "body_text"
                    if band["kind"] == "body"
                    else "table"
                    if band["kind"] == "table"
                    else "non_text"
                ),
                "page": stream_blocks[0]["page"],
                "column": stream_blocks[0]["column"],
                "bbox": {
                    "x_min": round(column.x_min, 2),
                    "y_min": round(y_min, 2),
                    "x_max": round(column.x_max, 2),
                    "y_max": round(y_max, 2),
                },
            }
        )
    return refined


def refine_blocks_with_band_clusters(
    blocks: Sequence[dict],
    page_image: Image.Image,
    columns_by_output_index: dict[int, Column],
    page_scan_lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    refined: list[dict] = []
    stream: list[dict] = []
    current_key: tuple[int, int] | None = None

    def flush_stream() -> None:
        nonlocal stream
        if not stream:
            return
        column = columns_by_output_index.get(stream[0]["column"])
        if column is None:
            refined.extend(stream)
        else:
            refined.extend(refine_stream_with_band_clusters(stream, page_image, column, page_scan_lines, scale_x, scale_y))
        stream = []

    for block in ordered:
        key = (block["page"], block["column"])
        if current_key is None or key == current_key:
            stream.append(block)
            current_key = key
            continue
        flush_stream()
        stream.append(block)
        current_key = key
    flush_stream()
    return refined


def classify_line_group_kind(
    page_image: Image.Image,
    column: Column,
    lines: Sequence[Line],
    scan_lines: Sequence[Line],
    scale_x: float,
    scale_y: float,
) -> str:
    region_lines = list(scan_lines) or list(lines)
    if not region_lines:
        return "text"

    bbox = {
        "x_min": column.x_min,
        "y_min": min(line.y_min for line in lines),
        "x_max": column.x_max,
        "y_max": max(line.y_max for line in lines),
    }
    left, top, right, bottom = bbox_to_px(bbox, scale_x, scale_y)
    if right - left < 10 or bottom - top < 10:
        return "text"

    crop = page_image.crop((left, top, right, bottom)).convert("L")
    data = np.asarray(crop)
    dark = data < 235
    suspicious_lines = find_suspicious_ocr_lines(region_lines)
    mask = build_text_mask(dark.shape, bbox, region_lines, scale_x, scale_y, suspicious_lines)

    residual = dark & ~mask
    residual_area = int(residual.sum())
    total_area = int(residual.shape[0] * residual.shape[1])
    line_count = len(region_lines)
    column_width = max(1.0, column.x_max - column.x_min)
    avg_line_width_ratio = sum((line.x_max - line.x_min) / column_width for line in region_lines) / max(1, line_count)
    max_line_width_ratio = max((line.x_max - line.x_min) / column_width for line in region_lines)
    compact_lengths = [len(re.sub(r"\s+", "", line.text)) for line in region_lines]
    short_ratio = sum(1 for length in compact_lengths if length <= 8) / max(1, line_count)
    centers = [((line.x_min + line.x_max) / 2.0 - column.x_min) / column_width for line in region_lines]
    center_spread = max(centers) - min(centers) if centers else 0.0
    group_height = max(line.y_max for line in region_lines) - min(line.y_min for line in region_lines)

    if all(OPTION_RE.match(line.text) for line in region_lines):
        return "text"

    # 线稿图中的 OCR 标注通常是若干短文本，集中分布在栏中部。
    if (
        line_count >= 3
        and short_ratio >= 0.75
        and avg_line_width_ratio <= 0.22
        and max_line_width_ratio <= 0.35
        and center_spread <= 0.33
        and group_height >= 40.0
    ):
        return "image"
    if residual_area <= max(80, int(total_area * 0.003)):
        return "text"

    ys, xs = np.where(residual)
    if len(xs) == 0 or len(ys) == 0:
        return "text"

    residual_width = int(xs.max() - xs.min() + 1)
    residual_height = int(ys.max() - ys.min() + 1)
    width_ratio = residual_width / max(1, residual.shape[1])
    height_ratio = residual_height / max(1, residual.shape[0])
    area_ratio = residual_area / max(1, total_area)

    # Long multi-line正文块优先判为文字，避免图下说明被整块吞进图片区。
    if line_count >= 5 and avg_line_width_ratio >= 0.42 and area_ratio < 0.08:
        return "text"
    if line_count >= 8 and avg_line_width_ratio >= 0.3 and area_ratio < 0.12:
        return "text"

    if area_ratio >= 0.015 and (width_ratio >= 0.2 or height_ratio >= 0.45):
        return "image"
    if residual_area >= max(160, int(total_area * 0.02)) and width_ratio >= 0.12:
        return "image"
    return "text"


def split_text_band_groups(lines: Sequence[Line], column: Column) -> list[list[Line]]:
    if not lines:
        return []
    return split_groups_on_structure_lines(
        split_groups_on_layout_shift(
            split_groups_on_question_anchors(cluster_lines_vertically(lines, max_gap=10.0)),
            column,
        )
    )


def split_blocks_at_boundaries(
    blocks: Sequence[dict],
    boundaries: Sequence[float],
    min_part_height: float = 8.0,
) -> list[dict]:
    if not blocks or not boundaries:
        return list(blocks)

    sorted_boundaries = sorted(boundaries)
    split_blocks: list[dict] = []
    for block in blocks:
        parts = [block]
        for boundary in sorted_boundaries:
            next_parts: list[dict] = []
            for part in parts:
                y_min = part["bbox"]["y_min"]
                y_max = part["bbox"]["y_max"]
                if not (y_min + min_part_height < boundary < y_max - min_part_height):
                    next_parts.append(part)
                    continue

                upper = {
                    **part,
                    "bbox": {
                        **part["bbox"],
                        "y_max": round(boundary, 2),
                    },
                }
                lower = {
                    **part,
                    "bbox": {
                        **part["bbox"],
                        "y_min": round(boundary, 2),
                    },
                }
                next_parts.extend([upper, lower])
            parts = next_parts
        split_blocks.extend(parts)
    return split_blocks


def resolve_label_blocks(blocks: Sequence[dict], page_lines: Sequence[Line]) -> list[dict]:
    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    resolved: list[dict] = [dict(block) for block in ordered]
    for idx, block in enumerate(resolved):
        if block.get("kind") != "label_text":
            continue

        prev_block = resolved[idx - 1] if idx > 0 else None
        next_block = resolved[idx + 1] if idx + 1 < len(resolved) else None
        prev_kind = prev_block.get("kind") if prev_block else None
        next_kind = next_block.get("kind") if next_block else None
        region_lines = lines_in_rect(
            page_lines,
            block["bbox"]["x_min"],
            block["bbox"]["x_max"],
            block["bbox"]["y_min"],
            block["bbox"]["y_max"],
        )
        compact_texts = [re.sub(r"\s+", "", line.text) for line in region_lines]
        has_structure = any(STRUCTURE_BREAK_RE.match(line.text) for line in region_lines)
        has_option = any(OPTION_RE.match(line.text) for line in region_lines)
        width = max(1.0, block["bbox"]["x_max"] - block["bbox"]["x_min"])
        centers = [((line.x_min + line.x_max) / 2.0 - block["bbox"]["x_min"]) / width for line in region_lines]
        center_spread = max(centers) - min(centers) if centers else 0.0
        avg_width_ratio = (
            sum((line.x_max - line.x_min) / width for line in region_lines) / max(1, len(region_lines))
        )
        mostly_short = sum(1 for text in compact_texts if len(text) <= 6) >= max(1, len(compact_texts) * 0.7)

        target_kind = "body_text"
        if has_option or has_structure:
            target_kind = "body_text"
        elif prev_kind and prev_kind == next_kind and prev_kind != "label_text":
            target_kind = prev_kind
        elif prev_kind == "non_text" and next_kind == "body_text":
            target_kind = "non_text" if (mostly_short or avg_width_ratio <= 0.42) and center_spread <= 0.45 else "body_text"
        elif prev_kind == "body_text" and next_kind == "non_text":
            target_kind = "body_text" if has_option or avg_width_ratio >= 0.28 else "non_text"
        elif prev_kind == "non_text" and next_kind is None:
            target_kind = "non_text" if avg_width_ratio <= 0.45 or center_spread <= 0.45 else "body_text"
        elif next_kind == "non_text" and prev_kind is None:
            target_kind = "non_text" if avg_width_ratio <= 0.45 or center_spread <= 0.45 else "body_text"
        elif prev_kind == "non_text" or next_kind == "non_text":
            target_kind = "non_text" if (mostly_short or avg_width_ratio <= 0.32) and center_spread <= 0.45 else "body_text"
        elif prev_kind and prev_kind != "label_text":
            target_kind = prev_kind
        elif next_kind and next_kind != "label_text":
            target_kind = next_kind
        elif mostly_short and center_spread <= 0.35:
            target_kind = "non_text"

        block["kind"] = target_kind
    return resolved


def resolve_mixed_blocks(blocks: Sequence[dict], page_lines: Sequence[Line]) -> list[dict]:
    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    resolved: list[dict] = [dict(block) for block in ordered]
    for idx, block in enumerate(resolved):
        if block.get("kind") != "mixed":
            continue

        region_lines = lines_in_rect(
            page_lines,
            block["bbox"]["x_min"],
            block["bbox"]["x_max"],
            block["bbox"]["y_min"],
            block["bbox"]["y_max"],
        )
        if any(OPTION_RE.match(line.text) for line in region_lines):
            block["kind"] = "body_text"
            continue

        prev_block = resolved[idx - 1] if idx > 0 else None
        next_block = resolved[idx + 1] if idx + 1 < len(resolved) else None
        prev_kind = prev_block.get("kind") if prev_block else None
        next_kind = next_block.get("kind") if next_block else None
        if prev_kind == "body_text" or next_kind == "body_text":
            block["kind"] = "body_text"
        elif prev_kind == "non_text" and next_kind == "non_text":
            block["kind"] = "non_text"
        else:
            block["kind"] = "body_text"
    return resolved


def reclassify_visual_text_blocks(blocks: Sequence[dict], page_lines: Sequence[Line]) -> list[dict]:
    adjusted: list[dict] = [dict(block) for block in blocks]
    for block in adjusted:
        if block.get("kind") != "body_text":
            continue
        region_lines = lines_in_rect(
            page_lines,
            block["bbox"]["x_min"],
            block["bbox"]["x_max"],
            block["bbox"]["y_min"],
            block["bbox"]["y_max"],
        )
        if not region_lines:
            continue
        pseudo_column = Column(
            index=0,
            x_min=block["bbox"]["x_min"],
            x_max=block["bbox"]["x_max"],
            start_x=block["bbox"]["x_min"],
        )
        hint_lines = find_visual_hint_lines(region_lines, pseudo_column)
        if any(OPTION_RE.match(line.text) or STRUCTURE_BREAK_RE.match(line.text) for line in region_lines):
            continue
        if len(hint_lines) >= max(1, len(region_lines) - 1):
            block["kind"] = "non_text"
    return adjusted


def absorb_inline_rule_blocks(
    blocks: Sequence[dict],
    page_lines: Sequence[Line],
    max_height: float = 10.0,
    max_gap: float = 8.0,
    require_next_body_text: bool = False,
) -> list[dict]:
    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    adjusted: list[dict] = [dict(block) for block in ordered]
    for idx, block in enumerate(adjusted):
        if block.get("kind") != "non_text":
            continue

        bbox = block["bbox"]
        height = bbox["y_max"] - bbox["y_min"]
        if height > max_height:
            continue

        prev_block = adjusted[idx - 1] if idx > 0 else None
        if not prev_block:
            continue
        same_prev = prev_block["page"] == block["page"] and prev_block["column"] == block["column"]
        if not same_prev:
            continue
        if prev_block.get("kind") != "body_text":
            continue

        gap_top = bbox["y_min"] - prev_block["bbox"]["y_max"]
        if gap_top > max_gap:
            continue

        if require_next_body_text:
            next_block = adjusted[idx + 1] if idx + 1 < len(adjusted) else None
            if not next_block:
                continue
            same_next = next_block["page"] == block["page"] and next_block["column"] == block["column"]
            if not same_next or next_block.get("kind") != "body_text":
                continue
            gap_bottom = next_block["bbox"]["y_min"] - bbox["y_max"]
            if gap_bottom > max_gap:
                continue

        block["kind"] = "body_text"
    return adjusted


def build_column_blocks(
    page_no: int,
    column: Column,
    page_image: Image.Image,
    page_lines: Sequence[Line],
    scan_lines: Sequence[Line],
    column_top: float,
    column_bottom: float,
    footer_top: float,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    column_lines = lines_in_rect(
        scan_lines,
        column.x_min,
        column.x_max,
        column_top,
        column_bottom,
    )
    groups = split_groups_on_structure_lines(
        split_groups_on_layout_shift(
            split_groups_on_question_anchors(cluster_lines_vertically(column_lines, max_gap=10.0)),
            column,
        )
    )
    blocks: list[dict] = []

    def append_block(kind: str, y_min: float, y_max: float) -> None:
        if y_max - y_min < 4.0:
            return
        blocks.append(
            {
                "kind": kind,
                "page": page_no,
                "column": column.index + 1,
                "bbox": {
                    "x_min": round(column.x_min, 2),
                    "y_min": round(max(column_top, y_min), 2),
                    "x_max": round(column.x_max, 2),
                    "y_max": round(min(column_bottom, y_max), 2),
                },
            }
        )

    def append_line_group(group_lines: list[Line]) -> None:
        if not group_lines:
            return
        group_bbox = {
            "x_min": column.x_min,
            "y_min": min(line.y_min for line in group_lines),
            "x_max": column.x_max,
            "y_max": max(line.y_max for line in group_lines),
        }
        region_scan_lines = lines_in_rect(
            scan_lines,
            column.x_min,
            column.x_max,
            group_bbox["y_min"] - 4.0,
            group_bbox["y_max"] + 4.0,
        )
        kind = classify_line_group_kind(page_image, column, group_lines, region_scan_lines, scale_x, scale_y)
        if kind != "text":
            append_block(
                "non_text",
                min(line.y_min for line in group_lines) - 2.0,
                max(line.y_max for line in group_lines) + 2.0,
            )
            return

        row_bands = split_region_by_row_kind(
            page_image,
            column,
            group_lines,
            region_scan_lines,
            group_bbox,
            scale_x,
            scale_y,
        )
        for band_kind, band_y_min, band_y_max in row_bands:
            append_block(band_kind, band_y_min - 1.0, band_y_max + 1.0)

    if not groups:
        return blocks

    prev_bottom = 20.0
    for group in groups:
        group_top = min(line.y_min for line in group)
        gap_bands = detect_non_text_bands(
            page_image,
            column.x_min,
            column.x_max,
            prev_bottom + 2.0,
            group_top - 3.0,
            scale_x,
            scale_y,
        )
        for band_y_min, band_y_max in gap_bands:
            append_block("non_text", band_y_min, band_y_max)
        append_line_group(group)
        prev_bottom = max(prev_bottom, max(line.y_max for line in group))

    trailing_bands = detect_non_text_bands(
        page_image,
        column.x_min,
        column.x_max,
        prev_bottom + 2.0,
        footer_top,
        scale_x,
        scale_y,
    )
    for band_y_min, band_y_max in trailing_bands:
        append_block("non_text", band_y_min, band_y_max)
    return blocks


def split_region_into_parts(
    region: dict,
    page_lines: Sequence[Line],
    page_image: Image.Image,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    bbox = region["bbox"]
    region_lines = lines_in_rect(
        page_lines,
        bbox["x_min"],
        bbox["x_max"],
        bbox["y_min"],
        bbox["y_max"],
    )
    groups = cluster_lines_vertically(region_lines)
    parts: list[dict] = []

    def append_text_block(text_lines: list[Line]) -> None:
        if not text_lines:
            return
        parts.append(
            {
                "page": region["page"],
                "column": region["column"],
                "bbox": {
                    "x_min": bbox["x_min"],
                    "y_min": round(max(bbox["y_min"], min(line.y_min for line in text_lines) - 2.0), 2),
                    "x_max": bbox["x_max"],
                    "y_max": round(min(bbox["y_max"], max(line.y_max for line in text_lines) + 2.0), 2),
                },
            }
        )

    if not groups:
        for band_y_min, band_y_max in detect_non_text_bands(
            page_image,
            bbox["x_min"],
            bbox["x_max"],
            bbox["y_min"],
            bbox["y_max"],
            scale_x,
            scale_y,
        ):
            parts.append(
                {
                    "page": region["page"],
                    "column": region["column"],
                    "bbox": {
                        "x_min": bbox["x_min"],
                        "y_min": round(band_y_min, 2),
                        "x_max": bbox["x_max"],
                        "y_max": round(band_y_max, 2),
                    },
                }
            )
        return parts or [region]

    pending_text: list[Line] = []

    top_gap_bands = detect_non_text_bands(
        page_image,
        bbox["x_min"],
        bbox["x_max"],
        bbox["y_min"],
        max(bbox["y_min"], min(line.y_min for line in groups[0]) - 3.0),
        scale_x,
        scale_y,
    )
    for band_y_min, band_y_max in top_gap_bands:
        parts.append(
            {
                "page": region["page"],
                "column": region["column"],
                "bbox": {
                    "x_min": bbox["x_min"],
                    "y_min": round(band_y_min, 2),
                    "x_max": bbox["x_max"],
                    "y_max": round(band_y_max, 2),
                },
            }
        )

    for idx, group in enumerate(groups):
        pending_text.extend(group)
        current_bottom = max(line.y_max for line in group)
        next_top = bbox["y_max"] if idx == len(groups) - 1 else min(line.y_min for line in groups[idx + 1])

        gap_bands = detect_non_text_bands(
            page_image,
            bbox["x_min"],
            bbox["x_max"],
            current_bottom + 2.0,
            next_top - 3.0,
            scale_x,
            scale_y,
        )
        if gap_bands:
            append_text_block(pending_text)
            pending_text = []
            for band_y_min, band_y_max in gap_bands:
                parts.append(
                    {
                        "page": region["page"],
                        "column": region["column"],
                        "bbox": {
                            "x_min": bbox["x_min"],
                            "y_min": round(band_y_min, 2),
                            "x_max": bbox["x_max"],
                            "y_max": round(band_y_max, 2),
                        },
                    }
                )

    append_text_block(pending_text)
    return parts or [region]


def merge_adjacent_image_blocks(blocks: Sequence[dict], max_gap: float = 30.0) -> list[dict]:
    if not blocks:
        return []

    merged: list[dict] = []
    for block in sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"])):
        if not merged:
            merged.append(block)
            continue

        prev = merged[-1]
        same_stream = prev["page"] == block["page"] and prev["column"] == block["column"]
        both_image = prev.get("kind") == "non_text" and block.get("kind") == "non_text"
        gap = block["bbox"]["y_min"] - prev["bbox"]["y_max"]
        if same_stream and both_image and gap <= max_gap:
            prev["bbox"]["y_max"] = max(prev["bbox"]["y_max"], block["bbox"]["y_max"])
            prev["bbox"]["x_min"] = min(prev["bbox"]["x_min"], block["bbox"]["x_min"])
            prev["bbox"]["x_max"] = max(prev["bbox"]["x_max"], block["bbox"]["x_max"])
        else:
            merged.append(block)
    return merged


def merge_visual_sequences(
    blocks: Sequence[dict],
    page_lines: Sequence[Line],
    max_gap: float = 18.0,
    tiny_text_height: float = 24.0,
) -> list[dict]:
    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    merged: list[dict] = []
    i = 0
    while i < len(ordered):
        current = ordered[i]
        if current.get("kind") != "non_text":
            merged.append(current)
            i += 1
            continue

        start = i
        end = i
        saw_tail_image = False
        j = i + 1
        while j < len(ordered):
            prev = ordered[j - 1]
            candidate = ordered[j]
            same_stream = prev["page"] == candidate["page"] and prev["column"] == candidate["column"]
            gap = candidate["bbox"]["y_min"] - prev["bbox"]["y_max"]
            if not same_stream or gap > max_gap:
                break
            if candidate.get("kind") == "non_text":
                saw_tail_image = True
                end = j
                j += 1
                continue
            if candidate.get("kind") == "body_text":
                height = candidate["bbox"]["y_max"] - candidate["bbox"]["y_min"]
                candidate_lines = lines_in_rect(
                    page_lines,
                    candidate["bbox"]["x_min"],
                    candidate["bbox"]["x_max"],
                    candidate["bbox"]["y_min"],
                    candidate["bbox"]["y_max"],
                )
                if height <= tiny_text_height and (
                    not candidate_lines
                    or not all(STRUCTURE_BREAK_RE.match(line.text) for line in candidate_lines)
                ):
                    end = j
                    j += 1
                    continue
            break

        if end > start and (saw_tail_image or ordered[end].get("kind") == "non_text"):
            group = ordered[start : end + 1]
            merged.append(
                {
                    "kind": "non_text",
                    "page": current["page"],
                    "column": current["column"],
                    "bbox": {
                        "x_min": min(item["bbox"]["x_min"] for item in group),
                        "y_min": min(item["bbox"]["y_min"] for item in group),
                        "x_max": max(item["bbox"]["x_max"] for item in group),
                        "y_max": max(item["bbox"]["y_max"] for item in group),
                    },
                }
            )
            i = end + 1
            continue

        merged.append(current)
        i += 1
    return merged


def merge_adjacent_text_blocks(blocks: Sequence[dict], max_gap: float = 26.0) -> list[dict]:
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    merged: list[dict] = []
    for block in ordered:
        if not merged:
            merged.append(block)
            continue

        prev = merged[-1]
        same_stream = prev["page"] == block["page"] and prev["column"] == block["column"]
        both_text = prev.get("kind") == "body_text" and block.get("kind") == "body_text"
        gap = block["bbox"]["y_min"] - prev["bbox"]["y_max"]
        if (
            same_stream
            and both_text
            and gap <= max_gap
            and not prev.get("no_merge_with_next")
            and not block.get("no_merge_with_prev")
        ):
            prev["bbox"]["y_max"] = max(prev["bbox"]["y_max"], block["bbox"]["y_max"])
            prev["bbox"]["x_min"] = min(prev["bbox"]["x_min"], block["bbox"]["x_min"])
            prev["bbox"]["x_max"] = max(prev["bbox"]["x_max"], block["bbox"]["x_max"])
        else:
            merged.append(block)
    return merged


def normalize_block_boundaries(blocks: Sequence[dict], min_height: float = 4.0) -> list[dict]:
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    normalized: list[dict] = [dict(ordered[0])]
    for block in ordered[1:]:
        current = dict(block)
        prev = normalized[-1]
        same_stream = prev["page"] == current["page"] and prev["column"] == current["column"]
        if same_stream and current["bbox"]["y_min"] < prev["bbox"]["y_max"]:
            cut_y = round((prev["bbox"]["y_max"] + current["bbox"]["y_min"]) / 2.0, 2)
            prev_height = cut_y - prev["bbox"]["y_min"]
            current_height = current["bbox"]["y_max"] - cut_y
            if prev_height >= min_height and current_height >= min_height:
                prev["bbox"]["y_max"] = cut_y
                current["bbox"]["y_min"] = cut_y
            elif prev_height < min_height and current_height >= min_height:
                normalized[-1] = current
                continue
            elif current_height < min_height and prev_height >= min_height:
                continue
            else:
                prev["bbox"]["y_max"] = max(prev["bbox"]["y_max"], current["bbox"]["y_max"])
                continue
        normalized.append(current)
    return normalized


def absorb_small_internal_gaps(
    blocks: Sequence[dict],
    gap_lines_source: Sequence[Line],
    max_gap: float = 40.0,
) -> list[dict]:
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))
    adjusted: list[dict] = [dict(block) for block in ordered]
    merged: list[dict] = []
    idx = 0
    while idx < len(adjusted):
        current = adjusted[idx]
        if idx == len(adjusted) - 1:
            merged.append(current)
            break

        nxt = adjusted[idx + 1]
        same_stream = current["page"] == nxt["page"] and current["column"] == nxt["column"]
        if not same_stream:
            merged.append(current)
            idx += 1
            continue

        gap = nxt["bbox"]["y_min"] - current["bbox"]["y_max"]
        if gap <= 0 or gap > max_gap:
            merged.append(current)
            idx += 1
            continue

        gap_lines = lines_in_rect(
            gap_lines_source,
            min(current["bbox"]["x_min"], nxt["bbox"]["x_min"]),
            max(current["bbox"]["x_max"], nxt["bbox"]["x_max"]),
            current["bbox"]["y_max"],
            nxt["bbox"]["y_min"],
        )
        if gap_lines:
            merged.append(current)
            idx += 1
            continue

        if current.get("kind") == nxt.get("kind"):
            current["bbox"]["y_max"] = nxt["bbox"]["y_max"]
            current["bbox"]["x_min"] = min(current["bbox"]["x_min"], nxt["bbox"]["x_min"])
            current["bbox"]["x_max"] = max(current["bbox"]["x_max"], nxt["bbox"]["x_max"])
            adjusted[idx + 1] = current
            idx += 1
            continue

        if nxt.get("kind") == "non_text" and current.get("kind") != "non_text":
            nxt["bbox"]["y_min"] = current["bbox"]["y_max"]
        elif current.get("kind") == "non_text" and nxt.get("kind") != "non_text":
            current["bbox"]["y_max"] = nxt["bbox"]["y_min"]
        else:
            cut_y = round((current["bbox"]["y_max"] + nxt["bbox"]["y_min"]) / 2.0, 2)
            current["bbox"]["y_max"] = cut_y
            nxt["bbox"]["y_min"] = cut_y
        merged.append(current)
        idx += 1
    return merged


def merge_tiny_bridge_blocks(
    blocks: Sequence[dict],
    page_lines: Sequence[Line],
    max_height: float = 12.0,
    max_gap: float = 40.0,
) -> list[dict]:
    if not blocks:
        return []

    ordered = [dict(block) for block in sorted(blocks, key=lambda item: (item["page"], item["column"], item["bbox"]["y_min"]))]
    merged: list[dict] = []
    idx = 0
    while idx < len(ordered):
        current = ordered[idx]
        prev = merged[-1] if merged else None
        nxt = ordered[idx + 1] if idx + 1 < len(ordered) else None

        current_height = current["bbox"]["y_max"] - current["bbox"]["y_min"]
        same_prev = prev and prev["page"] == current["page"] and prev["column"] == current["column"]
        same_next = nxt and nxt["page"] == current["page"] and nxt["column"] == current["column"]

        if (
            current_height <= max_height
            and same_prev
            and same_next
            and current["bbox"]["y_min"] - prev["bbox"]["y_max"] <= max_gap
            and nxt["bbox"]["y_min"] - current["bbox"]["y_max"] <= max_gap
        ):
            region_lines = lines_in_rect(
                page_lines,
                current["bbox"]["x_min"],
                current["bbox"]["x_max"],
                current["bbox"]["y_min"],
                current["bbox"]["y_max"],
            )
            has_structure = any(
                QUESTION_RE.match(line.text) or OPTION_RE.match(line.text) or STRUCTURE_BREAK_RE.match(line.text)
                for line in region_lines
            )
            if not has_structure:
                if prev.get("kind") == nxt.get("kind"):
                    prev["bbox"]["y_max"] = nxt["bbox"]["y_max"]
                    prev["bbox"]["x_min"] = min(prev["bbox"]["x_min"], current["bbox"]["x_min"], nxt["bbox"]["x_min"])
                    prev["bbox"]["x_max"] = max(prev["bbox"]["x_max"], current["bbox"]["x_max"], nxt["bbox"]["x_max"])
                    idx += 2
                    continue
                if prev.get("kind") == "non_text" and current.get("kind") != "body_text":
                    prev["bbox"]["y_max"] = current["bbox"]["y_max"]
                    prev["bbox"]["x_min"] = min(prev["bbox"]["x_min"], current["bbox"]["x_min"])
                    prev["bbox"]["x_max"] = max(prev["bbox"]["x_max"], current["bbox"]["x_max"])
                    idx += 1
                    continue
                if nxt.get("kind") == "non_text" and current.get("kind") != "body_text":
                    nxt["bbox"]["y_min"] = prev["bbox"]["y_max"]
                    idx += 1
                    continue

        merged.append(current)
        idx += 1
    return merged


def split_blocks_on_structure_lines(blocks: Sequence[dict], page_lines: Sequence[Line]) -> list[dict]:
    split_blocks: list[dict] = []
    for block in blocks:
        bbox = block["bbox"]
        region_lines = lines_in_rect(
            page_lines,
            bbox["x_min"],
            bbox["x_max"],
            bbox["y_min"],
            bbox["y_max"],
        )
        if block.get("kind") == "body_text":
            structure_lines = sorted(
                [
                    line
                    for line in region_lines
                    if STRUCTURE_BREAK_RE.match(line.text) and not QUESTION_RE.match(line.text)
                ],
                key=lambda line: (line.y_min, line.x_min),
            )
        else:
            structure_lines = sorted(
                [line for line in region_lines if OPTION_RE.match(line.text)],
                key=lambda line: (line.y_min, line.x_min),
            )

        if not structure_lines or len(structure_lines) == len(region_lines):
            split_blocks.append(block)
            continue

        first_structure_y = min(line.y_min for line in structure_lines)
        before_lines = [
            line for line in region_lines if (line.y_min + line.y_max) / 2 < first_structure_y
        ]
        if not before_lines:
            split_blocks.append(block)
            continue

        top_block = {
            **block,
            "no_merge_with_next": True,
            "bbox": {
                "x_min": bbox["x_min"],
                "y_min": bbox["y_min"],
                "x_max": bbox["x_max"],
                "y_max": round(max(line.y_max for line in before_lines) + 2.0, 2),
            },
        }
        option_block = {
            **block,
            "kind": "body_text",
            "no_merge_with_prev": True,
            "bbox": {
                "x_min": bbox["x_min"],
                "y_min": round(first_structure_y - 2.0, 2),
                "x_max": bbox["x_max"],
                "y_max": bbox["y_max"],
            },
        }
        split_blocks.extend([top_block, option_block])
    return split_blocks


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


def normalize_text(lines: Sequence[Line]) -> str:
    ordered = sorted(lines, key=lambda line: (round(line.y_min, 1), line.x_min))
    return "\n".join(line.text for line in ordered)


def compute_column_vertical_bounds(
    column: Column,
    page_lines: Sequence[Line],
    footer_top: float,
    column_anchors: Sequence[Anchor],
) -> tuple[float, float]:
    column_lines = [
        line
        for line in lines_in_rect(page_lines, column.x_min, column.x_max, 20.0, footer_top)
        if line.text.strip()
    ]
    if not column_lines:
        return 20.0, footer_top

    groups = cluster_lines_vertically(column_lines, max_gap=12.0)
    group_infos = [
        {
            "lines": group,
            "y_min": min(line.y_min for line in group),
            "y_max": max(line.y_max for line in group),
            "is_section": has_section_title(group),
        }
        for group in groups
    ]

    if not column_anchors:
        meaningful_groups = [group for group in group_infos if not group["is_section"]]
        if not meaningful_groups:
            return 20.0, footer_top
        top = max(20.0, meaningful_groups[0]["y_min"] - 4.0)
        bottom = min(footer_top, meaningful_groups[-1]["y_max"] + 8.0)
        if bottom <= top + 20.0:
            return 20.0, footer_top
        return round(top, 2), round(bottom, 2)

    def find_group_index_for_anchor(anchor: Anchor) -> int:
        for idx, info in enumerate(group_infos):
            if info["y_min"] - 4.0 <= anchor.y_min <= info["y_max"] + 4.0:
                return idx
        return min(range(len(group_infos)), key=lambda idx: abs(group_infos[idx]["y_min"] - anchor.y_min))

    first_anchor_idx = find_group_index_for_anchor(column_anchors[0])
    last_anchor_idx = find_group_index_for_anchor(column_anchors[-1])

    top_idx = first_anchor_idx
    for idx in range(first_anchor_idx, -1, -1):
        if not group_infos[idx]["is_section"]:
            top_idx = idx
        else:
            if idx != first_anchor_idx:
                break

    bottom_idx = last_anchor_idx
    for idx in range(last_anchor_idx, len(group_infos)):
        if not group_infos[idx]["is_section"]:
            bottom_idx = idx
        else:
            if idx != last_anchor_idx:
                break

    top = max(20.0, group_infos[top_idx]["y_min"] - 4.0)
    if group_infos[top_idx]["is_section"]:
        top = max(20.0, column_anchors[0].y_min - 6.0)
    bottom = min(footer_top, group_infos[bottom_idx]["y_max"] + 8.0)
    if bottom <= top + 20.0:
        return 20.0, footer_top
    return round(top, 2), round(bottom, 2)


def largest_true_rectangle(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    在布尔矩阵中寻找面积最大的全 True 矩形，返回 `(top, left, bottom, right)`，
    其中 `bottom/right` 为开区间。
    """
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


def largest_true_rectangle_touching_edge(mask: np.ndarray, edge: str) -> tuple[int, int, int, int] | None:
    """
    在布尔矩阵中寻找贴着指定边缘的最大全 True 矩形。
    返回 `(top, left, bottom, right)`，其中 `bottom/right` 为开区间。
    `edge` 只支持 `top` 或 `bottom`。
    """
    if mask.size == 0:
        return None
    if edge not in {"top", "bottom"}:
        raise ValueError(f"unsupported edge: {edge}")

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
                top = row - h + 1
                bottom = row + 1
                if edge == "top" and top != 0:
                    continue
                if edge == "bottom" and bottom != height:
                    continue
                area = h * (right - left)
                if area > best_area:
                    best_area = area
                    best_rect = (top, left, bottom, right)
            stack.append(idx)

    return best_rect


def full_width_blank_run_touching_edge(mask: np.ndarray, edge: str) -> tuple[int, int, int, int] | None:
    """
    仅寻找贴着顶部/底部、且宽度必须覆盖整栏宽度的空白矩形。
    本质上就是找整行全空白的连续 run。
    返回 `(top, 0, bottom, width)`，其中 `bottom` 为开区间。
    """
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


def find_anchor_left_blank_rectangle(
    page_image: Image.Image,
    column: Column,
    anchor_min: float,
    footer_top: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float] | None:
    """
    在 `anchor_min` 左侧寻找最大的矩形空白区域，返回：
    - 空白区左边缘
    - 空白区上边缘
    - 空白区右边缘
    - 空白区下边缘
    """
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
    fallback_bounds: dict[int, tuple[float, float]] = {}
    blank_rects: dict[int, tuple[float, float, float, float] | None] = {}

    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min)
        fallback_bounds[column.index] = compute_column_vertical_bounds(
            column,
            page_lines,
            footer_top,
            column_anchors,
        )
        if not column_anchors:
            blank_rects[column.index] = None
            continue
        anchor_min = min(anchor.x_min for anchor in column_anchors)
        blank_rects[column.index] = find_anchor_left_blank_rectangle(
            page_image,
            column,
            anchor_min,
            footer_top,
            scale_x,
            scale_y,
        )

    question1_y_min: float | None = None
    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min)
        for anchor in column_anchors:
            if anchor.question_no == "1":
                question1_y_min = find_question_top_from_anchor(
                    page_image,
                    column,
                    anchor.y_min,
                    20.0,
                    scale_x,
                    scale_y,
                )
                break
        if question1_y_min is not None:
            break

    for idx, column in enumerate(columns):
        rect = blank_rects.get(column.index)
        fallback_top, fallback_bottom = fallback_bounds[column.index]

        left = column.x_min
        right = column.x_max
        top = fallback_top
        bottom = fallback_bottom

        if rect is not None:
            rect_left, rect_top, rect_right, rect_bottom = rect
            left = rect_right
            top = rect_top
            bottom = rect_bottom

        if idx + 1 < len(columns):
            right_rect = blank_rects.get(columns[idx + 1].index)
            if right_rect is not None:
                top = max(top, right_rect[1])

        if idx == 0 and question1_y_min is not None:
            top = max(top, question1_y_min)

        effective_columns[column.index] = Column(
            index=column.index,
            x_min=round(left, 2),
            x_max=round(right, 2),
            start_x=column.start_x,
        )
        vertical_bounds[column.index] = (round(top, 2), round(bottom, 2))

    for idx in range(1, len(columns)):
        rect = blank_rects.get(columns[idx].index)
        if rect is None:
            continue
        prev_column = effective_columns[columns[idx - 1].index]
        curr_column = effective_columns[columns[idx].index]
        new_prev_right = clamp(rect[0], prev_column.x_min + 1.0, prev_column.x_max)
        new_curr_left = clamp(curr_column.x_min, new_prev_right + 1.0, curr_column.x_max)
        effective_columns[columns[idx - 1].index] = Column(
            index=prev_column.index,
            x_min=prev_column.x_min,
            x_max=round(new_prev_right, 2),
            start_x=prev_column.start_x,
        )
        effective_columns[columns[idx].index] = Column(
            index=curr_column.index,
            x_min=round(new_curr_left, 2),
            x_max=curr_column.x_max,
            start_x=curr_column.start_x,
        )

    for column in columns:
        effective = effective_columns[column.index]
        top, bottom = vertical_bounds[column.index]
        refined = refine_column_vertical_bounds_by_projection(
            page_image,
            effective,
            top,
            bottom,
            scale_x,
            scale_y,
        )
        vertical_bounds[column.index] = refined

    return effective_columns, vertical_bounds


def refine_column_vertical_bounds_by_projection(
    page_image: Image.Image,
    column: Column,
    top: float,
    bottom: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float]:
    """
    在已有栏框基础上，用整栏 `soft` 二值图的 y 投影去掉顶部/底部连续空白。
    """
    bbox = {
        "x_min": round(column.x_min, 2),
        "y_min": round(top, 2),
        "x_max": round(column.x_max, 2),
        "y_max": round(bottom, 2),
    }
    dark = get_clean_dark_crop(page_image, bbox, scale_x, scale_y, mode="soft")
    if dark is None or dark.shape[0] < 4 or dark.shape[1] < 4:
        return round(top, 2), round(bottom, 2)

    blank_mask = ~dark
    top_rect = full_width_blank_run_touching_edge(blank_mask, "top")
    bottom_rect = full_width_blank_run_touching_edge(blank_mask, "bottom")

    refined_top = top
    refined_bottom = bottom
    if top_rect is not None:
        refined_top = clamp(top + (top_rect[2] / scale_y), top, bottom)
    if bottom_rect is not None:
        refined_bottom = clamp(top + (bottom_rect[0] / scale_y), refined_top + 0.1, bottom)
    return round(refined_top, 2), round(refined_bottom, 2)


def find_gutter_empty_run(
    page_image: Image.Image,
    left_x: float,
    right_x: float,
    footer_top: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float] | None:
    separator_x = (left_x + right_x) / 2.0
    half_width = 10.0
    gutter_bbox = {
        "x_min": separator_x - half_width,
        "y_min": 20.0,
        "x_max": separator_x + half_width,
        "y_max": footer_top,
    }
    dark = get_clean_dark_crop(page_image, gutter_bbox, scale_x, scale_y, mode="strict")
    if dark is None or dark.shape[0] < 20 or dark.shape[1] < 4:
        return None

    row_dark = dark.sum(axis=1)
    empty_threshold = max(1, int(dark.shape[1] * 0.06))
    empty = row_dark <= empty_threshold

    min_run = max(24, int(dark.shape[0] * 0.08))
    best: tuple[int, int] | None = None
    start: int | None = None
    for idx, value in enumerate(empty):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            if idx - start >= min_run and (best is None or idx - start > best[1] - best[0]):
                best = (start, idx)
            start = None
    if start is not None and len(empty) - start >= min_run:
        if best is None or len(empty) - start > best[1] - best[0]:
            best = (start, len(empty))

    if best is None:
        return None

    top = 20.0 + (best[0] / scale_y)
    bottom = 20.0 + (best[1] / scale_y)
    if bottom <= top + 20.0:
        return None
    return round(top, 2), round(bottom, 2)


def compute_column_vertical_bounds_with_gutters(
    columns: Sequence[Column],
    page_image: Image.Image,
    page_lines: Sequence[Line],
    footer_top: float,
    anchors_by_column: dict[int, list[Anchor]],
    scale_x: float,
    scale_y: float,
) -> dict[int, tuple[float, float]]:
    fallback_bounds = {
        column.index: compute_column_vertical_bounds(
            column,
            page_lines,
            footer_top,
            sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min),
        )
        for column in columns
    }

    gutter_runs: dict[tuple[int, int], tuple[float, float]] = {}
    for left_column, right_column in zip(columns, columns[1:]):
        run = find_gutter_empty_run(
            page_image,
            left_column.x_max,
            right_column.x_min,
            footer_top,
            scale_x,
            scale_y,
        )
        if run is not None:
            gutter_runs[(left_column.index, right_column.index)] = run

    final_bounds: dict[int, tuple[float, float]] = {}
    for column in columns:
        candidate_runs: list[tuple[float, float]] = []
        if (column.index - 1, column.index) in gutter_runs:
            candidate_runs.append(gutter_runs[(column.index - 1, column.index)])
        if (column.index, column.index + 1) in gutter_runs:
            candidate_runs.append(gutter_runs[(column.index, column.index + 1)])

        if not candidate_runs:
            final_bounds[column.index] = fallback_bounds[column.index]
            continue

        top = max(run[0] for run in candidate_runs)
        bottom = min(run[1] for run in candidate_runs)
        if bottom <= top + 20.0:
            final_bounds[column.index] = fallback_bounds[column.index]
            continue
        final_bounds[column.index] = (round(top, 2), round(bottom, 2))

    return final_bounds


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
    image_path: Path,
    crops_dir: Path,
    debug_dir: Path | None,
    scan_lines: Sequence[Line] | None = None,
    refine_with_band_clusters: bool = False,
) -> list[dict]:
    """
    按分栏分题结果（split_columns_questions）+ 题内 band 切分（split_question_bands）
    裁切每道题的图片并组装 manifest record 列表。

    与旧版 process_page 的主要区别：
    - 不再自行计算分栏/分题边界；委托给 compute_page_columns_and_questions。
    - 不再自行做 column block 裁切；委托给 split_question_segment_bands 做 band 级切分。
    - refine_with_band_clusters 参数保留以维持调用接口兼容，实际由 band 切分内部处理。
    """
    if not layout.is_exam_page:
        return []

    # Local import to break circular dependency:
    # split_columns_questions imports from rough_split_questions at module level.
    from split_columns_questions import compute_page_columns_and_questions
    from split_question_bands import (
        QuestionPage,
        split_question_segment_bands,
        compute_question_text_height,
    )

    page_no = layout.page_no
    image = Image.open(image_path)
    scale_x = image.width / layout.page_width
    scale_y = image.height / layout.page_height

    # Step 1: compute column/question layout via split_columns_questions
    page_record = compute_page_columns_and_questions(layout, image_path)
    questions = page_record.get("questions", [])
    if not questions:
        return []

    # Step 2: prepare scan lines for band detection
    page_scan_lines: list[Line] = list(scan_lines) if scan_lines is not None else list(layout.lines)
    question_text_height = compute_question_text_height(page_scan_lines)

    # Step 3: create QuestionPage descriptor.
    # DPI is derived from rendered image pixel size vs PDF pt size (strict dpi/72 convention).
    dpi_x = round(image.width / layout.page_width * 72.0, 4) if layout.page_width > 0 else 72.0
    dpi_y = round(image.height / layout.page_height * 72.0, 4) if layout.page_height > 0 else 72.0
    page_qp = QuestionPage(
        page_no=page_no,
        page_width=layout.page_width,
        page_height=layout.page_height,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
    )

    outputs: list[dict] = []
    debug_rects: list[tuple[str, float, float, float, float]] = []

    for question in questions:
        question_no = question["question_no"]
        question_bbox = question["bbox"]

        # OCR text assembled from PDF layer lines within the main question bbox
        crop_lines = lines_in_rect(
            layout.lines,
            question_bbox["x_min"], question_bbox["x_max"],
            question_bbox["y_min"], question_bbox["y_max"],
        )
        ocr_text = normalize_text(crop_lines)

        section_title = question.get("section", "")
        anchor_text = question.get("anchor_text", "")

        final_images: list[dict] = []
        part_index = 1

        for segment in question.get("segments", []):
            seg_bbox = segment["bbox"]
            seg_page_no = int(segment.get("page", page_no))
            seg_column = int(segment.get("column", 1))

            # Run band splitting on this question segment
            split_result = split_question_segment_bands(
                page_qp,
                image,
                segment,
                page_scan_lines,
                question_text_height,
            )

            # split_question_segment_bands returns [] when no scan lines are found
            # in the segment; fall back to cropping the whole segment as one image.
            merged_bands = (
                split_result.get("merged_bands") or []
            ) if isinstance(split_result, dict) else []

            if not merged_bands:
                left_px = max(0, int(seg_bbox["x_min"] * scale_x))
                top_px = max(0, int(seg_bbox["y_min"] * scale_y) - 2)
                right_px = min(image.width, int(seg_bbox["x_max"] * scale_x))
                bottom_px = min(image.height, int(seg_bbox["y_max"] * scale_y) + 2)
                if right_px > left_px and bottom_px > top_px:
                    output_name = build_part_name(page_no, question_no, part_index)
                    image.crop((left_px, top_px, right_px, bottom_px)).save(
                        crops_dir / output_name
                    )
                    final_images.append({
                        "path": str(Path("images") / output_name),
                        "type": "body",
                        "page": seg_page_no,
                        "column": seg_column,
                        "bbox": seg_bbox,
                    })
                    part_index += 1
                continue

            # Crop each merged band from the page image.
            # Band x coordinates are normalized to 0..column_width (origin = segment left edge).
            # Band y coordinates are in absolute PDF pt space (offset_y == 0 when local_bbox == bbox).
            for band in merged_bands:
                band_bbox = band["bbox"]
                left_px = max(0, int(seg_bbox["x_min"] * scale_x))
                right_px = min(image.width, int(seg_bbox["x_max"] * scale_x))
                top_px = max(0, int(float(band_bbox["y_min"]) * scale_y))
                bottom_px = min(image.height, int(float(band_bbox["y_max"]) * scale_y))

                # Small edge padding
                top_px = max(0, top_px - 2)
                bottom_px = min(image.height, bottom_px + 2)

                if right_px <= left_px or bottom_px <= top_px:
                    continue

                output_name = build_part_name(page_no, question_no, part_index)
                image.crop((left_px, top_px, right_px, bottom_px)).save(
                    crops_dir / output_name
                )

                band_kind = band.get("kind", "body")
                image_type = (
                    "body" if band_kind == "body"
                    else "table" if band_kind == "table"
                    else "visual"
                )
                final_images.append({
                    "path": str(Path("images") / output_name),
                    "type": image_type,
                    "page": seg_page_no,
                    "column": seg_column,
                    "bbox": {
                        "x_min": round(seg_bbox["x_min"], 2),
                        "y_min": round(float(band_bbox["y_min"]), 2),
                        "x_max": round(seg_bbox["x_max"], 2),
                        "y_max": round(float(band_bbox["y_max"]), 2),
                    },
                })
                part_index += 1

        debug_rects.append((
            f"Q{question_no}",
            question_bbox["x_min"], question_bbox["y_min"],
            question_bbox["x_max"], question_bbox["y_max"],
        ))

        outputs.append({
            "page": page_no,
            "question_no": question_no,
            "section": section_title,
            "images": final_images,
            "anchor_text": anchor_text,
            "ocr_text": ocr_text,
        })

    if debug_dir is not None and debug_rects:
        debug_path = debug_dir / f"page_{page_no:03d}_overlay.png"
        save_debug_overlay(image, debug_path, scale_x, scale_y, debug_rects)

    return sorted(outputs, key=lambda item: (item["page"], int(item["question_no"])))


def main() -> None:
    parser = argparse.ArgumentParser(description="按题号粗切试卷 PDF")
    parser.add_argument("pdf", help="源 PDF 路径")
    parser.add_argument(
        "--out",
        default="tmp/question_crops",
        help="输出目录，默认 tmp/question_crops",
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
    parser.add_argument(
        "--text-source",
        choices=("pdf", "surya", "hybrid"),
        default="hybrid",
        help="文字区域来源：pdf=仅 PDF 文字层；surya=仅 Surya detect 行框；hybrid=标准流程，锚点仍用 PDF、分块判别用 Surya detect",
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
    with tempfile.TemporaryDirectory(prefix="rough_split_") as tmp:
        tmp_dir = Path(tmp)
        render_dir = tmp_dir / "pages"
        render_dir.mkdir(parents=True, exist_ok=True)
        layouts_by_page: dict[int, PageLayout] = {}
        images_by_page: dict[int, Path] = {}
        for page_no in pages:
            layout = analyze_page_layout(pdf_path, page_no)
            layouts_by_page[page_no] = layout
            anchors_by_column = {column.index + 1: 0 for column in layout.columns}
            for anchor in layout.anchors:
                column = assign_column(anchor.x_min, layout.columns)
                if column is not None:
                    anchors_by_column[column.index + 1] += 1

            page_manifest.append(
                {
                    "page": page_no,
                    "is_exam_page": layout.is_exam_page,
                    "column_count": len(layout.columns),
                    "column_starts": [round(column.start_x, 2) for column in layout.columns],
                    "question_anchor_count": len(layout.anchors),
                    "question_numbers": [anchor.question_no for anchor in layout.anchors],
                    "anchors_per_column": anchors_by_column,
                    "sections": [section.title for section in layout.sections],
                    "reasons": layout.reasons,
                }
            )

            if not layout.is_exam_page:
                continue

            images_by_page[page_no] = render_page_image(pdf_path, page_no, render_dir, args.dpi)

        surya_lines_by_page: dict[int, list[Line]] = {}
        if args.text_source in {"surya", "hybrid"} and images_by_page:
            surya_lines_by_page = load_surya_lines(images_by_page, layouts_by_page)

        for page_no in pages:
            layout = layouts_by_page[page_no]
            if not layout.is_exam_page:
                continue

            image_path = images_by_page[page_no]
            if args.text_source == "pdf":
                scan_lines = layout.lines
            elif args.text_source == "surya":
                scan_lines = surya_lines_by_page.get(page_no) or layout.lines
            else:
                scan_lines = surya_lines_by_page.get(page_no) or layout.lines
            manifest.extend(
                process_page(
                    layout,
                    image_path,
                    crops_dir,
                    debug_dir,
                    scan_lines=scan_lines,
                    refine_with_band_clusters=args.text_source in {"surya", "hybrid"},
                )
            )

    manifest_path = out_dir / "manifest.json"
    page_manifest_path = out_dir / "page_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    page_manifest_path.write_text(json.dumps(page_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pages: {pages}")
    print(f"exam_pages: {sum(1 for item in page_manifest if item['is_exam_page'])}")
    print(f"questions: {len(manifest)}")
    print(f"text_source: {args.text_source}")
    print(f"page_manifest: {page_manifest_path}")
    print(f"manifest: {manifest_path}")
    print(f"images: {crops_dir}")


if __name__ == "__main__":
    main()
