#!/usr/bin/env python3
"""
独立执行“单题分块”。

输入方式：
1. 单页 PDF：默认把整页当作一道题。
2. 单张图片：默认把整张图当作一道题。
3. 分题模块输出：复用 `split_columns_questions.py` 的题目对象作为元数据来源；
   但分块输入本身仍然必须是一张完整单题页或图像，不再处理多段/跨栏拼接。

输出：
- bands.json：merge 前的 classified band 列表
- merged_bands.json：该题的 merged band 列表
- bands_overlay.png：原页叠图，标出 merge 前 bands
- overlay.png：原页叠图，标出 merged bands

模块边界：
- 不依赖整页 page layout / 分栏 / 分题逻辑。
- 页面级只做：
  - 单页渲染或直接读取单张图片
  - 页尺寸与 DPI 解析
  - Surya 检测框提取
- 题目元数据可以直接复用 `split_columns_questions.py` 的 question 记录：
  - `question_id`
  - `question_no`
- 但本模块不再消费 `segments` 做多段拼接；
- 每次只处理一张完整的单题页/单题图像。

坐标体系：
- 模块内部统一使用 `pt` 坐标。
- 坐标比例严格秉持物理换算：**`Scale = DPI / 72.0`**，禁止使用图像宽高反推，杜绝所有因像素化与浮点取整造成的坐标漂移和跨界污染。
- PDF 输入：
  - 先按给定 DPI 渲染成图像；
  - 通过 `DPI / 72.0` 在 PDF 的原生 `pt` 尺寸和图像像素空间内做无损双向映射。
- 图片输入：
  - 读取图片 DPI；若缺失，则使用默认 `180 DPI`；
  - 用 `pt = px * 72 / dpi` 把图片像素坐标换算成统一的 `pt` 坐标。

band 处理流程：
1. 行检测
  - 使用 Surya detection 提取文字框；
  - 当前不再依赖 PDF text layer；
  - 检测框文本仅用于占位，格式为 `TXT_n`。
2. 结构 band 切分
  - 先把同一文字行上的 Surya 检测框做横向合并；
  - 再在文字行之间切出初始 `text band / gap band`；
  - 相邻 band 计算 `connect_up / connect_down`；
  - 对任意存在 `up/down` 连通的 gap，通过高精度的防越界边界搜寻将其物理切分开来：
    - `up=1` 时，紧贴上方连通域的下边界落刀，保留上方带物体切片；
    - `down=1` 时，紧贴下方连通域的上边界落刀，保留下方带物体切片；
    - 最终使得缝隙被切分为完全真空的 `empty_gap` 与包裹残余图元的 `visual_gap`，且像素矩阵严格不重叠。
3. band 分类
  - `text band` 只分：
    - `table`
    - `label`
    - `body`
  - `gap band` 只分：
    - `empty_gap`
    - `line_gap`
    - `table_gap`
    - `visual_gap`
4. 正文流左对齐统计
  - 在分类前，收集所有 `text band` 的左侧对齐位置；
  - 左端点取自：该 `text band` 的无遮盖连通区域最左边缘；若没有有效连通区域，则回退到最左文字；
  - 用 `int(x_min / question_text_height)` 统计文字距离桶 `0..6`；
  - 取计数最大的桶；若并列，保留靠前的两个；
  - 输出到 `body_flow_left_stats`，便于调试正文流。
5. body 修正
  - 在 merge 前，自上而下扫描所有 `body`；
  - 使用无遮盖连通区域的左边缘；
  - 若其位于 `body_flow_left_mark` 右侧，且最近距离超过 `3 * question_text_height`；
  - 则把该 `body` 改成 `label`。
6. band 合并
  - 先做“前置连通性合并”：
    - 所有 `line_gap` 先强制设置 `connect_up = 1`；
    - 连续的同类 `text band`（`body/table/label`）直接合并；
    - 所有与相邻 `body/table` 连通的 gap，直接并入该 `body/table`；
    - 若 gap 与相邻 `label` 连通，则比较两者“无遮盖连通区域在 x 轴上的投影长度 × band 高度”：
      - 面积较大的那一侧决定合并后的类型；
    - 递归执行，直到没有新的连通性合并。
  - 再做“围绕core收敛spacer”：
  - `core = {body, table, visual_gap}`
  - `spacer = {empty_gap, line_gap, table_gap, label}`
  - 按 core/spacer 关系递归吸收，直到稳定。
  - 当前收敛规则只保留：
    - 开头/结尾的 `spacer` 可并入相邻 `core`
    - `body/table + spacer + 同类 body/table` 直接三段合并
    - 相邻同类 `core` 可继续合并
  - 之后按顺序处理残留：
    - `table_gap -> visual_gap`
    - 残留 `line_gap` 吸收到前一个 `empty_gap/label`
    - 连续 spacer 中只要含 `label`，整段压成一个 `label`
    - 最后把残留 `empty_gap/label` 并入相邻 `table/visual_gap`
    - 再做一次收敛
  - 目标是最终只剩：
    - `body`
    - `table`
    - `visual_gap`

TODO
- 评估 `text band` 是否需要直接识别出 `visual`，而不只是在 `body/table/label` 中三选一。
"""

from __future__ import annotations

import argparse
import cv2
import json
import os
import numpy as np
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_IMAGE_DPI = 180.0
_COLUMN_DARK_CACHE: dict[tuple[int, int, int, str], np.ndarray] = {}


@dataclass(frozen=True)
class Line:
    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class Column:
    index: int
    x_min: float
    x_max: float
    start_x: float


@dataclass(frozen=True)
class QuestionPage:
    page_no: int
    page_width: float
    page_height: float
    dpi_x: float
    dpi_y: float


def run_cmd(args: list[str], *, capture: bool = True) -> str:
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


def get_total_pages(pdf_path: Path) -> int:
    text = run_cmd(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Pages:\s+(\d+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("failed to parse page count from pdfinfo")
    return int(match.group(1))


def parse_page_info(pdf_path: Path, page_no: int) -> QuestionPage:
    info_text = run_cmd(["pdfinfo", "-f", str(page_no), "-l", str(page_no), str(pdf_path)])
    match = re.search(r"Page(?:\s+\d+)?\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)\s+pts", info_text)
    if not match:
        raise RuntimeError(f"failed to parse page size for page {page_no}")
    return QuestionPage(
        page_no=page_no,
        page_width=float(match.group(1)),
        page_height=float(match.group(2)),
        dpi_x=72.0,
        dpi_y=72.0,
    )


def parse_image_page_info(image_path: Path, default_dpi: float = DEFAULT_IMAGE_DPI) -> QuestionPage:
    with Image.open(image_path) as image:
        width, height = image.size
        dpi = image.info.get("dpi")
    if isinstance(dpi, tuple) and len(dpi) >= 2:
        dpi_x = float(dpi[0] or default_dpi)
        dpi_y = float(dpi[1] or default_dpi)
    else:
        dpi_x = float(default_dpi)
        dpi_y = float(default_dpi)
    return QuestionPage(
        page_no=1,
        page_width=float(width) * 72.0 / dpi_x,
        page_height=float(height) * 72.0 / dpi_y,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
    )


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


def overlap_length(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return max(0.0, min(a_max, b_max) - max(a_min, b_min))


def lines_in_rect(
    lines,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> list[Line]:
    return [
        line
        for line in lines
        if line.x_max >= x_min and line.x_min <= x_max and line.y_max >= y_min and line.y_min <= y_max
    ]


def bbox_to_px(bbox: dict[str, float], scale_x: float, scale_y: float) -> tuple[int, int, int, int]:
    left = int(bbox["x_min"] * scale_x)
    top = int(bbox["y_min"] * scale_y)
    right = int(bbox["x_max"] * scale_x)
    bottom = int(bbox["y_max"] * scale_y)
    return left, top, right, bottom


def merge_detected_line_bands(lines: list[Line]) -> list[dict]:
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


def compute_question_text_height(lines: list[Line]) -> float:
    if not lines:
        return 0.0

    ordered = sorted(lines, key=lambda line: (line.y_min, line.x_min))
    first = ordered[0]
    first_row: list[Line] = [first]
    row_mid = (first.y_min + first.y_max) / 2.0
    row_height = max(1.0, first.y_max - first.y_min)

    for line in ordered[1:]:
        line_mid = (line.y_min + line.y_max) / 2.0
        vertical_overlap = overlap_length(
            first.y_min,
            first.y_max,
            line.y_min,
            line.y_max,
        )
        if (
            abs(line_mid - row_mid) <= max(8.0, row_height * 0.8)
            or vertical_overlap >= min(row_height, max(1.0, line.y_max - line.y_min)) * 0.35
        ):
            first_row.append(line)
            continue
        break

    keep_count = max(1, (len(first_row) + 1) // 2)
    kept = sorted(first_row, key=lambda line: (line.x_max - line.x_min), reverse=True)[:keep_count]
    return round(max(line.y_max - line.y_min for line in kept), 2)


def expand_line_bands(
    line_bands: list[dict],
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


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def component_box_area(comp: dict[str, int | float]) -> int:
    return int(comp["width"]) * int(comp["height"])


def stats_box_area(stats: np.ndarray, label_id: int) -> int:
    return int(stats[label_id, cv2.CC_STAT_WIDTH]) * int(stats[label_id, cv2.CC_STAT_HEIGHT])


def projected_shadow_area(components: list[dict[str, int | float]], band_height_px: int) -> int:
    if band_height_px <= 0 or not components:
        return 0
    intervals = sorted(
        ((int(comp["left"]), int(comp["left"]) + int(comp["width"])) for comp in components if int(comp["width"]) > 0),
        key=lambda item: (item[0], item[1]),
    )
    if not intervals:
        return 0
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    shadow_width = sum(max(0, end - start) for start, end in merged)
    return int(shadow_width * band_height_px)


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


class QuestionConnectedComponentsCache:
    """
    题目级连通区域缓存。

    构造时直接接收：
    - 已生成的整题二值图 `dark_image`
    - Surya 检测框列表 `text_boxes`
    - `scale_x/scale_y`

    对外提供统一接口：
    - `find_connected_components(y_min, y_max, mask_text)`

    说明：
    - 当前按“整题全宽”切片；
    - key 只区分：
      - `y_min`
      - `y_max`
      - `mask_text`
    """

    def __init__(
        self,
        dark_image: np.ndarray,
        text_boxes: list[Line],
        scale_x: float,
        scale_y: float,
        *,
        text_pad_px: int = 1,
    ) -> None:
        self.dark_image = dark_image.astype(np.uint8)
        self.text_boxes = list(text_boxes)
        self.scale_x = float(scale_x)
        self.scale_y = float(scale_y)
        self.text_pad_px = int(text_pad_px)
        self._cache: dict[tuple[float, float, bool], dict[str, object]] = {}

    def find_connected_components(
        self,
        y_min: float,
        y_max: float,
        mask_text: bool,
    ) -> dict[str, object]:
        cache_key = (round(float(y_min), 2), round(float(y_max), 2), bool(mask_text))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        top = max(0, int(float(y_min) * self.scale_y))
        bottom = min(self.dark_image.shape[0], int(float(y_max) * self.scale_y))
        if bottom - top < 2:
            result = {
                "dark": None,
                "masked_dark": None,
                "num_labels": 0,
                "labels": None,
                "stats": None,
                "centroids": None,
                "components": [],
            }
            self._cache[cache_key] = result
            return result

        dark = self.dark_image[top:bottom, :]
        masked = dark.copy()
        crop_height, crop_width = masked.shape[:2]
        if crop_width <= 0 or crop_height <= 0:
            result = {
                "dark": dark.astype(bool),
                "masked_dark": masked.astype(bool),
                "num_labels": 0,
                "labels": None,
                "stats": None,
                "centroids": None,
                "components": [],
            }
            self._cache[cache_key] = result
            return result

        if mask_text:
            for line in self.text_boxes:
                line_left = int(line.x_min * self.scale_x)
                line_right = int(line.x_max * self.scale_x)
                line_top = int(line.y_min * self.scale_y)
                line_bottom = int(line.y_max * self.scale_y)
                x0 = max(0, line_left - self.text_pad_px)
                x1 = min(crop_width, line_right + self.text_pad_px)
                y0 = max(0, line_top - top - self.text_pad_px)
                y1 = min(crop_height, line_bottom - top + self.text_pad_px)
                if x1 <= x0 or y1 <= y0:
                    continue
                masked[y0:y1, x0:x1] = 0

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(masked.astype(np.uint8), connectivity=8)
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

        result = {
            "dark": dark.astype(bool),
            "masked_dark": masked.astype(bool),
            "num_labels": int(num_labels),
            "labels": labels,
            "stats": stats,
            "centroids": centroids,
            "components": components,
        }
        self._cache[cache_key] = result
        return result

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


def detect_table_band_signal(
    components_info: dict[str, object],
    *,
    connect_up: bool = False,
    connect_down: bool = False,
) -> bool:
    masked_dark = components_info.get("masked_dark")
    labels = components_info.get("labels")
    components = components_info.get("components") or []
    if masked_dark is None or not isinstance(masked_dark, np.ndarray) or labels is None or not components:
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
        bottom_touch = comp_bottom >= height - 1 and bool(edge_mask[max(0, height - 2):].any())
        return top_touch, bottom_touch

    left_component = min(components, key=lambda comp: (int(comp["left"]), -int(comp["height"])))
    right_component = max(components, key=lambda comp: (int(comp["left"]) + int(comp["width"]), int(comp["height"])))

    left_up, left_down = component_touches_vertical_edge(left_component, "left")
    right_up, right_down = component_touches_vertical_edge(right_component, "right")
    if left_up != right_up or left_down != right_down:
        return False
    if left_up and not connect_up:
        return False
    if left_down and not connect_down:
        return False
    return left_up or left_down


def detect_line_gap_signal(components_info: dict[str, object], scale_y: float) -> bool:
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
        comp_top_pt = comp_top / max(scale_y, 1e-6)
        if comp_top_pt > 3.0:
            return False
    return True


def has_spanning_component(
    components_cache: QuestionConnectedComponentsCache,
    y_min: float,
    y_max: float,
) -> bool:
    components_info = components_cache.find_connected_components(y_min, y_max, False)
    dark = components_info.get("masked_dark")
    if dark is None or not dark.any():
        return False

    num_labels = int(components_info.get("num_labels") or 0)
    labels = components_info.get("labels")
    stats = components_info.get("stats")
    if num_labels <= 1:
        return False
    if labels is None or stats is None:
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
    bands: list[dict],
    components_cache: QuestionConnectedComponentsCache,
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
        if has_spanning_component(components_cache, window_y_min, window_y_max):
            upper["connect_down"] = True
            lower["connect_up"] = True
    return connected


def find_visual_gap_content_parts(
    components_cache: QuestionConnectedComponentsCache,
    y_min: float,
    y_max: float,
    scale_y: float,
) -> list[tuple[float, float]]:
    components_info = components_cache.find_connected_components(y_min, y_max, False)
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
        ((int(comp["top"]), int(comp["top"]) + int(comp["height"])) for comp in components),
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
            parts.append((part_y_min, part_y_max))
    return parts


def split_connected_gap_band_on_blank(
    components_cache: QuestionConnectedComponentsCache,
    y_min: float,
    y_max: float,
    scale_y: float,
    connect_up: bool,
    connect_down: bool,
) -> list[tuple[float, float, bool, bool]]:
    if not (connect_up or connect_down):
        return [(y_min, y_max, connect_up, connect_down)]
    parts = find_visual_gap_content_parts(components_cache, y_min, y_max, scale_y)
    if not parts:
        return [(y_min, y_max, connect_up, connect_down)]

    top_end = parts[0][1]
    bottom_start = parts[-1][0]
    top_split = bool(connect_up and top_end > y_min + 0.5)
    bottom_split = bool(connect_down and bottom_start < y_max - 0.5)
    if top_split and bottom_split and bottom_start <= top_end + 0.5:
        bottom_split = False
    if not top_split and not bottom_split:
        return [(y_min, y_max, connect_up, connect_down)]

    split_points = [y_min]
    if top_split:
        split_points.append(top_end)
    if bottom_split and bottom_start > split_points[-1] + 0.5:
        split_points.append(bottom_start)
    if y_max > split_points[-1] + 0.5:
        split_points.append(y_max)

    if len(split_points) < 3:
        return [(y_min, y_max, connect_up, connect_down)]

    segments: list[tuple[float, float, bool, bool]] = []
    for idx, (start, end) in enumerate(zip(split_points[:-1], split_points[1:])):
        if end <= start + 0.5:
            continue
        seg_up = connect_up if idx == 0 else False
        seg_down = connect_down if idx == len(split_points) - 2 else False
        segments.append((start, end, seg_up, seg_down))

    if len(segments) < 2:
        return [(y_min, y_max, connect_up, connect_down)]
    return segments


def build_structural_bands(
    line_bands: list[dict],
    page_image: Image.Image,
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    region_y_min: float,
    region_y_max: float,
    scale_x: float,
    scale_y: float,
) -> list[dict]:
    bands: list[dict] = []
    previous_y = region_y_min
    band_index = 0

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

    bands = assign_pairwise_band_connectivity(bands, components_cache, scale_y)

    split_bands: list[dict] = []
    next_index = 0
    for band in bands:
        if band["band_type"] == "gap" and (band.get("connect_up") or band.get("connect_down")):
            for gap_y_min, gap_y_max, connect_up, connect_down in split_connected_gap_band_on_blank(
                components_cache,
                band["bbox"]["y_min"],
                band["bbox"]["y_max"],
                scale_y,
                connect_up=bool(band.get("connect_up")),
                connect_down=bool(band.get("connect_down")),
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

    return assign_pairwise_band_connectivity(split_bands, components_cache, scale_y)


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
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    scale_x: float,
    scale_y: float,
    band_context: dict | None = None,
    prev_band: dict | None = None,
) -> str:
    lines = line_band["lines"]
    components_info = components_cache.find_connected_components(line_band["y_min"], line_band["y_max"], True)
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
    column_width = max(1.0, column.x_max - column.x_min)
    body_like_left = ((text_x_min - column.x_min) / column_width) <= 0.18
    body_like_width = ((text_x_max - text_x_min) / column_width) >= 0.3

    if (connect_up or connect_down) and not (body_like_left and body_like_width):
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
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    y_min: float,
    y_max: float,
    scale_y: float,
    band_context: dict | None = None,
    prev_band: dict | None = None,
) -> str:
    components_info = components_cache.find_connected_components(y_min, y_max, False)
    masked_dark = components_info.get("masked_dark")
    band_area_px = int(masked_dark.size) if isinstance(masked_dark, np.ndarray) else 0
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 4 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
    ]
    component_area = sum(component_box_area(comp) for comp in components)

    is_line_gap = detect_line_gap_signal(components_info, scale_y)
    height_delta = y_max - y_min
    thresh = max(20, int(band_area_px * 0.002))
    if y_min > 525 and y_max < 535:
        print(f"TRACER inside classify for {y_min}-{y_max}:")
        print(f"  height: {height_delta}, area: {band_area_px}, comp_area: {component_area}, thresh: {thresh}")
        print(f"  comps: {len(components)}")
        for i, c in enumerate(components):
            print(f"    c[{i}]: {c}")

    if is_line_gap:
        return "line_gap"
    if height_delta <= 3.0:
        return "empty_gap"
    if component_area <= thresh:
        return "empty_gap"
    return "visual_gap"


def classify_text_band_in_sequence(
    band: dict,
    prev_band: dict | None,
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> dict:
    item = dict(band)
    line_band = item["line_band"]
    text_metrics = compute_text_band_metrics(line_band, components_cache, column, scale_x, scale_y)
    item["semantic_area"] = text_metrics["semantic_area"]
    item["text_shadow_width_px"] = text_metrics["text_shadow_width_px"]
    item["kind"] = classify_text_line_band(
        line_band,
        components_cache,
        column,
        scale_x,
        scale_y,
        band_context=band,
        prev_band=prev_band,
    )
    return item


def compute_text_band_metrics(
    line_band: dict,
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> dict:
    lines = line_band["lines"]
    text_x_min = min(line.x_min for line in lines)
    text_shadow_width_px = 0
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
        text_shadow_width_px += max(0, line_right - line_left)
        text_area_px += max(0, line_right - line_left) * max(0, line_bottom - line_top)
    components_info = components_cache.find_connected_components(line_band["y_min"], line_band["y_max"], True)
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 6 and int(comp["width"]) >= 2 and int(comp["height"]) >= 2
    ]
    if components:
        component_left = min(column.x_min + int(comp["left"]) / scale_x for comp in components)
    else:
        component_left = text_x_min
    unmasked_components_info = components_cache.find_connected_components(line_band["y_min"], line_band["y_max"], False)
    unmasked_components = [
        comp
        for comp in (unmasked_components_info.get("components") or [])
        if component_box_area(comp) >= 6 and int(comp["width"]) >= 2 and int(comp["height"]) >= 2
    ]
    unmasked_dark = unmasked_components_info.get("masked_dark")
    unmasked_band_height_px = int(unmasked_dark.shape[0]) if isinstance(unmasked_dark, np.ndarray) else 0
    return {
        "semantic_area": text_area_px + sum(component_box_area(comp) for comp in components),
        "component_left": component_left,
        "text_shadow_width_px": int(text_shadow_width_px),
    }


def compute_unmasked_text_band_left(
    line_band: dict,
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> float:
    lines = line_band["lines"]
    text_x_min = min(line.x_min for line in lines)
    components_info = components_cache.find_connected_components(line_band["y_min"], line_band["y_max"], False)
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 6 and int(comp["width"]) >= 2 and int(comp["height"]) >= 2
    ]
    if components:
        return min(column.x_min + int(comp["left"]) / scale_x for comp in components)
    return text_x_min


def classify_gap_band_in_sequence(
    band: dict,
    prev_band: dict | None,
    components_cache: QuestionConnectedComponentsCache,
    column: Column,
    scale_x: float,
    scale_y: float,
) -> dict:
    item = dict(band)
    components_info = components_cache.find_connected_components(item["bbox"]["y_min"], item["bbox"]["y_max"], False)
    masked_dark = components_info.get("masked_dark")
    components = [
        comp
        for comp in (components_info.get("components") or [])
        if component_box_area(comp) >= 4 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
    ]
    item["semantic_area"] = sum(component_box_area(comp) for comp in components)
    item["kind"] = classify_gap_band_kind(
        components_cache,
        column,
        item["bbox"]["y_min"],
        item["bbox"]["y_max"],
        scale_y,
        band_context=band,
        prev_band=prev_band,
    )
    return item


def classify_bands_in_order(
    structural_bands: list[dict],
    components_cache: QuestionConnectedComponentsCache,
    page_image: Image.Image,
    column: Column,
    scale_x: float,
    scale_y: float,
    question_text_height: float,
) -> tuple[list[dict], dict]:
    def classify_once(sequence: list[dict]) -> list[dict]:
        classified_once: list[dict] = []
        for band in sequence:
            prev_band = classified_once[-1] if classified_once else None
            if band["band_type"] == "text":
                item = classify_text_band_in_sequence(band, prev_band, components_cache, column, scale_x, scale_y)
            else:
                item = classify_gap_band_in_sequence(band, prev_band, components_cache, column, scale_x, scale_y)
            classified_once.append(item)
        return classified_once

    def refine_body_adjacent_visual_gaps(classified_once: list[dict]) -> tuple[list[dict], bool]:
        refined: list[dict] = []
        changed = False
        next_index = 0

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
                components_cache,
                band["bbox"]["y_min"],
                band["bbox"]["y_max"],
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

    def apply_body_correction(classified_once: list[dict]) -> list[dict]:
        corrected: list[dict] = []
        body_flow_left_mark = [
            float(value)
            for value in body_flow_left_stats.get("body_flow_left_mark", [])
            if isinstance(value, (int, float))
        ]
        right_shift_threshold = max(0.0, 3.0 * float(question_text_height))
        for band in classified_once:
            item = dict(band)
            if item.get("kind") != "body":
                corrected.append(item)
                continue
            line_band = item.get("line_band")
            if line_band is not None:
                current_left = compute_unmasked_text_band_left(
                    line_band,
                    components_cache,
                    column,
                    scale_x,
                    scale_y,
                )
            else:
                current_left = None
            if not isinstance(current_left, (int, float)):
                corrected.append(item)
                continue
            item["body_left"] = round(float(current_left), 2)
            positive_deltas = [
                float(current_left) - mark
                for mark in body_flow_left_mark
                if float(current_left) > mark
            ]
            if positive_deltas and min(positive_deltas) > right_shift_threshold:
                item["kind"] = "label"
                item.pop("body_left", None)
            corrected.append(item)
        return corrected

    def compute_body_flow_left_stats(sequence: list[dict]) -> dict:
        bucket_x_mins: dict[int, list[float]] = {idx: [] for idx in range(7)}
        if question_text_height <= 0:
            return {
                "question_text_height": round(float(question_text_height), 2),
                "bucket_x_mins": bucket_x_mins,
                "dominant_buckets": [],
                "body_flow_left_mark": [],
                "sample_count": 0,
            }

        sample_count = 0
        for band in sequence:
            if band.get("band_type") != "text":
                continue
            current_left = compute_unmasked_text_band_left(
                band["line_band"],
                components_cache,
                column,
                scale_x,
                scale_y,
            )
            bucket = int(float(current_left) / float(question_text_height))
            if 0 <= bucket <= 6:
                bucket_x_mins[bucket].append(round(float(current_left), 2))
                sample_count += 1

        if sample_count == 0:
            dominant_buckets: list[int] = []
        else:
            max_count = max(len(bucket_x_mins[idx]) for idx in range(7))
            dominant_buckets = [idx for idx in range(7) if len(bucket_x_mins[idx]) == max_count and max_count > 0][:2]

        body_flow_left_mark = [
            round(min(bucket_x_mins[idx]), 2)
            for idx in dominant_buckets
            if bucket_x_mins[idx]
        ]

        return {
            "question_text_height": round(float(question_text_height), 2),
            "bucket_x_mins": bucket_x_mins,
            "dominant_buckets": dominant_buckets,
            "body_flow_left_mark": body_flow_left_mark,
            "sample_count": sample_count,
        }

    body_flow_left_stats = compute_body_flow_left_stats(structural_bands)
    classified = classify_once(structural_bands)
    refined_structural, changed = refine_body_adjacent_visual_gaps(classified)
    if not changed:
        pre_correction = classified
        corrected = apply_body_correction(pre_correction)
        corrected = assign_pairwise_band_connectivity(corrected, components_cache, scale_y)
        return corrected, body_flow_left_stats

    refined_structural = assign_pairwise_band_connectivity(refined_structural, components_cache, scale_y)
    pre_correction = classify_once(refined_structural)
    corrected = apply_body_correction(pre_correction)
    corrected = assign_pairwise_band_connectivity(corrected, components_cache, scale_y)
    return corrected, body_flow_left_stats


def merge_classified_bands(
    bands: list[dict],
    components_cache: QuestionConnectedComponentsCache,
    scale_y: float,
) -> tuple[list[dict], list[dict]]:
    core_kinds = {"body", "table", "visual_gap"}
    spacer_kinds = {"empty_gap", "line_gap", "table_gap", "label"}
    gap_kinds = {"empty_gap", "line_gap", "table_gap", "visual_gap"}

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

    def item_text_shadow_width(item: dict) -> int:
        return int(item.get("text_shadow_width_px", 0))

    def item_connectivity_profile(item: dict) -> tuple[int, int]:
        components_info = components_cache.find_connected_components(
            float(item["bbox"]["y_min"]),
            float(item["bbox"]["y_max"]),
            False,
        )
        components = [
            comp
            for comp in (components_info.get("components") or [])
            if component_box_area(comp) >= 4 and int(comp["width"]) >= 1 and int(comp["height"]) >= 1
        ]
        masked_dark = components_info.get("masked_dark")
        band_height_px = int(masked_dark.shape[0]) if isinstance(masked_dark, np.ndarray) else max(
            0, int(round((float(item["bbox"]["y_max"]) - float(item["bbox"]["y_min"])) * scale_y))
        )
        intervals = sorted(
            (
                (int(comp["left"]), int(comp["left"]) + int(comp["width"]))
                for comp in components
                if int(comp["width"]) > 0
            ),
            key=lambda item: (item[0], item[1]),
        )
        merged: list[list[int]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        shadow_width = sum(max(0, end - start) for start, end in merged)
        return int(shadow_width), int(band_height_px)

    def merge_items(group: list[dict], kind: str) -> dict:
        return {
            "kind": kind,
            "index": group[0]["index"],
            "band_type": group[0].get("band_type", "text"),
            "text": "\n".join(part for item in group for part in [item_text(item)] if part),
            "member_indices": [idx for item in group for idx in item_member_indices(item)],
            "member_kinds": [member_kind for item in group for member_kind in item_member_kinds(item)],
            "bbox": {
                "x_min": group[0]["bbox"]["x_min"],
                "y_min": min(item["bbox"]["y_min"] for item in group),
                "x_max": group[0]["bbox"]["x_max"],
                "y_max": max(item["bbox"]["y_max"] for item in group),
            },
            "connect_up": group[0].get("connect_up", False),
            "connect_down": group[-1].get("connect_down", False),
            "semantic_area": sum(item_semantic_area(item) for item in group),
            "text_shadow_width_px": sum(item_text_shadow_width(item) for item in group),
        }

    merge_trace: list[dict] = []

    def record_trace(stage: str, items: list[dict]) -> None:
        merge_trace.append(
            {
                "stage": stage,
                "bands": sanitize_bands_for_json(items),
            }
        )

    def converge_connectivity(items: list[dict]) -> list[dict]:
        merged_items = items
        round_idx = 0
        record_trace("connectivity:start", merged_items)
        changed = True
        while changed:
            changed = False
            next_bands: list[dict] = []
            idx = 0
            prev_gap_merged = False
            while idx < len(merged_items):
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in {"body", "table", "label"}
                    and merged_items[idx + 1]["kind"] == merged_items[idx]["kind"]
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx]["kind"]))
                    idx += 2
                    changed = True
                    prev_gap_merged = False
                    continue
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] == "label"
                    and merged_items[idx + 1]["kind"] in gap_kinds
                    and merged_items[idx + 1].get("connect_up", False)
                    and not prev_gap_merged
                ):
                    label_shadow_width = item_text_shadow_width(merged_items[idx])
                    label_band_height = max(
                        0,
                        int(round((float(merged_items[idx]["bbox"]["y_max"]) - float(merged_items[idx]["bbox"]["y_min"])) * scale_y)),
                    )
                    gap_shadow_width, gap_band_height = item_connectivity_profile(merged_items[idx + 1])
                    merged_kind = (
                        merged_items[idx + 1]["kind"]
                        if gap_shadow_width > label_shadow_width or gap_band_height > label_band_height
                        else "label"
                    )
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_kind))
                    idx += 2
                    changed = True
                    prev_gap_merged = True
                    continue
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in gap_kinds
                    and merged_items[idx + 1]["kind"] == "label"
                    and merged_items[idx].get("connect_down", False)
                ):
                    gap_shadow_width, gap_band_height = item_connectivity_profile(merged_items[idx])
                    label_shadow_width = item_text_shadow_width(merged_items[idx + 1])
                    label_band_height = max(
                        0,
                        int(round((float(merged_items[idx + 1]["bbox"]["y_max"]) - float(merged_items[idx + 1]["bbox"]["y_min"])) * scale_y)),
                    )
                    merged_kind = (
                        merged_items[idx]["kind"]
                        if gap_shadow_width > label_shadow_width or gap_band_height > label_band_height
                        else "label"
                    )
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_kind))
                    idx += 2
                    changed = True
                    prev_gap_merged = True
                    continue
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in {"body", "table"}
                    and merged_items[idx + 1]["kind"] in gap_kinds
                    and merged_items[idx + 1].get("connect_up", False)
                    and not prev_gap_merged
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx]["kind"]))
                    idx += 2
                    changed = True
                    prev_gap_merged = True
                    continue
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in gap_kinds
                    and merged_items[idx + 1]["kind"] in {"body", "table"}
                    and merged_items[idx].get("connect_down", False)
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx + 1]["kind"]))
                    idx += 2
                    changed = True
                    prev_gap_merged = True
                    continue
                next_bands.append(merged_items[idx])
                if merged_items[idx]["kind"] in gap_kinds:
                    prev_gap_merged = False
                idx += 1
            merged_items = next_bands
            round_idx += 1
            record_trace(f"connectivity:round_{round_idx}", merged_items)
        return merged_items

    def converge_core_spacer(items: list[dict]) -> list[dict]:
        merged_items = items
        round_idx = 0
        record_trace("core_spacer:start", merged_items)
        changed = True
        while changed:
            changed = False
            next_bands: list[dict] = []
            idx = 0
            while idx < len(merged_items):
                if (
                    idx == 0
                    and idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in spacer_kinds
                    and merged_items[idx + 1]["kind"] in core_kinds
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx + 1]["kind"]))
                    idx += 2
                    changed = True
                    continue
                if (
                    idx + 2 < len(merged_items)
                    and merged_items[idx]["kind"] in {"body", "table"}
                    and merged_items[idx + 1]["kind"] in spacer_kinds
                    and merged_items[idx + 2]["kind"] == merged_items[idx]["kind"]
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1], merged_items[idx + 2]], merged_items[idx]["kind"]))
                    idx += 3
                    changed = True
                    continue
                if (
                    idx == len(merged_items) - 2
                    and merged_items[idx]["kind"] in core_kinds
                    and merged_items[idx + 1]["kind"] in spacer_kinds
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx]["kind"]))
                    idx += 2
                    changed = True
                    continue
                if (
                    idx + 1 < len(merged_items)
                    and merged_items[idx]["kind"] in core_kinds
                    and merged_items[idx + 1]["kind"] == merged_items[idx]["kind"]
                ):
                    next_bands.append(merge_items([merged_items[idx], merged_items[idx + 1]], merged_items[idx]["kind"]))
                    idx += 2
                    changed = True
                    continue
                next_bands.append(merged_items[idx])
                idx += 1
            merged_items = next_bands
            round_idx += 1
            record_trace(f"core_spacer:round_{round_idx}", merged_items)
        return merged_items

    prepared_bands: list[dict] = []
    for band in bands:
        item = dict(band)
        if item.get("kind") == "line_gap":
            item["connect_up"] = True
        prepared_bands.append(item)
    record_trace("prepared", prepared_bands)

    merged_bands = converge_connectivity(prepared_bands)
    record_trace("after_connectivity", merged_bands)
    merged_bands = converge_core_spacer(merged_bands)
    record_trace("after_core_spacer", merged_bands)

    normalized_bands: list[dict] = []
    table_gap_downgraded = False
    for item in merged_bands:
        if item["kind"] == "table_gap":
            normalized_bands.append(merge_items([item], "visual_gap"))
            table_gap_downgraded = True
        else:
            normalized_bands.append(item)
    if table_gap_downgraded:
        record_trace("after_table_gap_downgrade", normalized_bands)
        normalized_bands = converge_core_spacer(normalized_bands)
        record_trace("after_table_gap_core_spacer", normalized_bands)

    line_gap_absorbed: list[dict] = []
    idx = 0
    line_gap_changed = False
    absorbable_prev_spacers = {"empty_gap", "label"}
    while idx < len(normalized_bands):
        item = normalized_bands[idx]
        if item["kind"] == "line_gap" and line_gap_absorbed and line_gap_absorbed[-1]["kind"] in absorbable_prev_spacers:
            prev_item = line_gap_absorbed.pop()
            line_gap_absorbed.append(merge_items([prev_item, item], prev_item["kind"]))
            line_gap_changed = True
            idx += 1
            continue
        line_gap_absorbed.append(item)
        idx += 1
    if line_gap_changed:
        record_trace("after_line_gap_absorb", line_gap_absorbed)
        line_gap_absorbed = converge_core_spacer(line_gap_absorbed)
        record_trace("after_line_gap_core_spacer", line_gap_absorbed)

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
        record_trace("after_label_spacer_collapse", collapsed_spacers)
        collapsed_spacers = converge_core_spacer(collapsed_spacers)
        record_trace("after_label_core_spacer", collapsed_spacers)

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
        record_trace("after_final_visual_table_absorb", absorbed_visual_table)
        absorbed_visual_table = converge_core_spacer(absorbed_visual_table)
        record_trace("after_final_core_spacer", absorbed_visual_table)

    record_trace("final", absorbed_visual_table)
    return absorbed_visual_table, merge_trace


def load_surya_detect_lines(
    image_map: dict[int, Path],
    pages: dict[int, QuestionPage],
    *,
    fallback_text: str = "TXT",
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
        page = pages[page_no]
        scale_x = 72.0 / page.dpi_x if page.dpi_x > 0 else 1.0
        scale_y = 72.0 / page.dpi_y if page.dpi_y > 0 else 1.0
        detected_lines: list[Line] = []
        for idx, detected_box in enumerate(result.bboxes):
            px_x_min, px_y_min, px_x_max, px_y_max = detected_box.bbox
            if px_x_max <= px_x_min or px_y_max <= px_y_min:
                continue
            bbox = (
                round(px_x_min * scale_x, 2),
                round(px_y_min * scale_y, 2),
                round(px_x_max * scale_x, 2),
                round(px_y_max * scale_y, 2),
            )
            text = f"{fallback_text}_{idx + 1}"
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


def normalize_merged_bands(
    merged_bands: list[dict],
    segment_bbox: dict[str, float],
    local_bbox: dict[str, float],
) -> list[dict]:
    normalized: list[dict] = []
    offset_y = float(local_bbox["y_min"]) - float(segment_bbox["y_min"])
    width = float(local_bbox["x_max"]) - float(local_bbox["x_min"])
    for idx, band in enumerate(merged_bands):
        y_min = band["bbox"]["y_min"]
        y_max = band["bbox"]["y_max"]
        if idx == 0:
            y_min = segment_bbox["y_min"]
        if idx == len(merged_bands) - 1:
            y_max = segment_bbox["y_max"]
        normalized.append(
            {
                **band,
                "kind": "visual" if band.get("kind") == "visual_gap" else band.get("kind"),
                "bbox": {
                    "x_min": 0.0,
                    "y_min": round(y_min + offset_y, 2),
                    "x_max": round(width, 2),
                    "y_max": round(y_max + offset_y, 2),
                },
            }
        )
    return normalized


def normalize_bands(
    bands: list[dict],
    segment_bbox: dict[str, float],
    local_bbox: dict[str, float],
) -> list[dict]:
    normalized: list[dict] = []
    offset_y = float(local_bbox["y_min"]) - float(segment_bbox["y_min"])
    width = float(local_bbox["x_max"]) - float(local_bbox["x_min"])
    for band in bands:
        normalized.append(
            {
                **band,
                "bbox": {
                    "x_min": 0.0,
                    "y_min": round(float(band["bbox"]["y_min"]) + offset_y, 2),
                    "x_max": round(width, 2),
                    "y_max": round(float(band["bbox"]["y_max"]) + offset_y, 2),
                },
            }
        )
    return normalized


def sanitize_bands_for_json(bands: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for band in bands:
        item = dict(band)
        line_band = item.pop("line_band", None)
        if line_band is not None:
            item["line_text"] = line_band.get("text", "")
        sanitized.append(item)
    return sanitized


def split_question_segment_bands(
    page: QuestionPage,
    page_image: Image.Image,
    segment: dict,
    page_scan_lines: list[Line],
    question_text_height: float,
) -> dict:
    scale_x = page.dpi_x / 72.0 if page.dpi_x > 0 else 1.0
    scale_y = page.dpi_y / 72.0 if page.dpi_y > 0 else 1.0
    bbox = segment["bbox"]
    local_bbox = segment.get("local_bbox", bbox)
    pseudo_column = Column(
        index=max(0, int(segment.get("column", 1)) - 1),
        x_min=float(bbox["x_min"]),
        x_max=float(bbox["x_max"]),
        start_x=float(bbox["x_min"]),
    )

    region_lines = [
        line
        for line in lines_in_rect(
            page_scan_lines,
            pseudo_column.x_min,
            pseudo_column.x_max,
            bbox["y_min"],
            bbox["y_max"],
        )
        if line.text.strip()
    ]
    if not region_lines:
        return []

    full_dark = get_clean_dark_crop(
        page_image,
        bbox,
        scale_x,
        scale_y,
        pad_y_px=0,
        mode="soft",
    )
    if full_dark is None:
        return []
    components_cache = QuestionConnectedComponentsCache(
        full_dark,
        region_lines,
        scale_x,
        scale_y,
        text_pad_px=1,
    )

    pad_pdf = 2.0 / scale_y
    raw_line_bands = merge_detected_line_bands(region_lines)
    line_bands = expand_line_bands(
        raw_line_bands,
        float(bbox["y_min"]),
        float(bbox["y_max"]),
        pad_pdf,
    )
    if not line_bands:
        return []

    bands = build_structural_bands(
        line_bands,
        page_image,
        components_cache,
        pseudo_column,
        float(bbox["y_min"]),
        float(bbox["y_max"]),
        scale_x,
        scale_y,
    )
    bands, body_flow_left_stats = classify_bands_in_order(
        bands,
        components_cache,
        page_image,
        pseudo_column,
        scale_x,
        scale_y,
        question_text_height,
    )
    merged_bands, merge_trace = merge_classified_bands(bands, components_cache, scale_y)
    bands = normalize_bands(bands, bbox, local_bbox)
    merged_bands = normalize_merged_bands(merged_bands, bbox, local_bbox)
    merged_bands = sanitize_bands_for_json(merged_bands)

    for band in bands:
        band["page"] = int(segment["page"])
        band["column"] = int(segment.get("column", 1))
    for band in merged_bands:
        band["page"] = int(segment["page"])
        band["column"] = int(segment.get("column", 1))
    return {
        "bands": bands,
        "merged_bands": merged_bands,
        "merge_trace": merge_trace,
        "body_flow_left_stats": body_flow_left_stats,
    }


def split_question_from_columns_question(
    question_input_path: Path,
    question_record: dict,
    *,
    dpi: int = 180,
    text_source: str = "surya",
) -> dict:
    if question_input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        result = split_single_image(question_input_path, text_source=text_source)
    else:
        result = split_single_page_pdf(question_input_path, dpi=dpi, text_source=text_source)
    result["question_id"] = str(question_record.get("question_id", result["question_id"]))
    result["question_no"] = str(question_record.get("question_no", result["question_no"]))
    return result


def split_question_from_record(
    question_input_path: Path,
    question_record: dict,
    *,
    dpi: int = 180,
    text_source: str = "surya",
) -> dict:
    return split_question_from_columns_question(
        question_input_path,
        question_record,
        dpi=dpi,
        text_source=text_source,
    )


def split_single_page_pdf(
    pdf_path: Path,
    *,
    dpi: int = 180,
    text_source: str = "surya",
) -> dict:
    total_pages = get_total_pages(pdf_path)
    if total_pages != 1:
        raise RuntimeError("single-page mode requires a PDF with exactly 1 page")

    with tempfile.TemporaryDirectory(prefix="split_question_page_") as tmp:
        tmp_dir = Path(tmp)
        render_dir = tmp_dir / "pages"
        render_dir.mkdir(parents=True, exist_ok=True)

        page_info = parse_page_info(pdf_path, 1)
        page = QuestionPage(
            page_no=page_info.page_no,
            page_width=page_info.page_width,
            page_height=page_info.page_height,
            dpi_x=float(dpi),
            dpi_y=float(dpi),
        )
        image_path = render_page_image(pdf_path, 1, render_dir, dpi)
        page_image = Image.open(image_path)

        if text_source in {"surya", "hybrid"}:
            surya_lines = load_surya_detect_lines({1: image_path}, {1: page}).get(1) or []
        else:
            surya_lines = []
        question_text_height = compute_question_text_height(surya_lines)

        question_record = {
            "question_id": "p001_q01",
            "question_no": "1",
            "segments": [
                {
                    "page": 1,
                    "column": 1,
                    "bbox": {
                        "x_min": 0.0,
                        "y_min": 0.0,
                        "x_max": round(page.page_width, 2),
                        "y_max": round(page.page_height, 2),
                    },
                    "kind": "single_page_question",
                    "local_bbox": {
                        "x_min": 0.0,
                        "y_min": 0.0,
                        "x_max": round(page.page_width, 2),
                        "y_max": round(page.page_height, 2),
                    },
                }
            ],
        }
        split_result = split_question_segment_bands(
            page,
            page_image,
            question_record["segments"][0],
            surya_lines,
            question_text_height,
        )
        return {
            "question_id": question_record["question_id"],
            "question_no": question_record["question_no"],
            "page_width": round(page.page_width, 2),
            "page_height": round(page.page_height, 2),
            "question_text_height": question_text_height,
            "body_flow_left_stats": split_result["body_flow_left_stats"],
            "merge_trace": split_result["merge_trace"],
            "segments": question_record["segments"],
            "bands": sanitize_bands_for_json(split_result["bands"]),
            "merged_bands": split_result["merged_bands"],
        }


def split_single_image(
    image_path: Path,
    *,
    text_source: str = "surya",
) -> dict:
    page = parse_image_page_info(image_path)
    page_image = Image.open(image_path).convert("RGB")

    if text_source in {"surya", "hybrid"}:
        surya_lines = load_surya_detect_lines({1: image_path}, {1: page}).get(1) or []
    else:
        surya_lines = []
    question_text_height = compute_question_text_height(surya_lines)

    question_record = {
        "question_id": "p001_q01",
        "question_no": "1",
        "segments": [
            {
                "page": 1,
                "column": 1,
                "bbox": {
                    "x_min": 0.0,
                    "y_min": 0.0,
                    "x_max": round(page.page_width, 2),
                    "y_max": round(page.page_height, 2),
                },
                "kind": "single_image_question",
                "local_bbox": {
                    "x_min": 0.0,
                    "y_min": 0.0,
                    "x_max": round(page.page_width, 2),
                    "y_max": round(page.page_height, 2),
                },
            }
        ],
    }
    split_result = split_question_segment_bands(
        page,
        page_image,
        question_record["segments"][0],
        surya_lines,
        question_text_height,
    )
    return {
        "question_id": question_record["question_id"],
        "question_no": question_record["question_no"],
        "page_width": round(page.page_width, 2),
        "page_height": round(page.page_height, 2),
        "question_text_height": question_text_height,
        "body_flow_left_stats": split_result["body_flow_left_stats"],
        "merge_trace": split_result["merge_trace"],
        "segments": question_record["segments"],
        "bands": sanitize_bands_for_json(split_result["bands"]),
        "merged_bands": split_result["merged_bands"],
    }


def draw_band_overlay(pdf_path: Path, result: dict, output_path: Path, *, dpi: int = 180, band_key: str = "merged_bands") -> None:
    with tempfile.TemporaryDirectory(prefix="split_question_overlay_") as tmp:
        render_dir = Path(tmp)
        page_width = float(result.get("page_width", 1.0))
        page_height = float(result.get("page_height", 1.0))
        first_page_no = int(result["segments"][0]["page"])
        first_image_path = render_page_image(pdf_path, first_page_no, render_dir, dpi)
        first_image = Image.open(first_image_path).convert("RGB")
        first_page_info = parse_page_info(pdf_path, first_page_no)
        first_page = QuestionPage(
            page_no=first_page_info.page_no,
            page_width=first_page_info.page_width,
            page_height=first_page_info.page_height,
            dpi_x=float(dpi),
            dpi_y=float(dpi),
        )
        base_scale_x = first_page.dpi_x / 72.0 if first_page.dpi_x > 0 else 1.0
        base_scale_y = first_page.dpi_y / 72.0 if first_page.dpi_y > 0 else 1.0

        canvas_width = max(1, int(round(page_width * base_scale_x)))
        canvas_height = max(1, int(round(page_height * base_scale_y)))
        image = Image.new("RGB", (canvas_width, canvas_height), "white")

        page_images: dict[int, Image.Image] = {first_page_no: first_image}
        page_infos: dict[int, QuestionPage] = {first_page_no: first_page}
        for segment in result["segments"]:
            page_no = int(segment["page"])
            if page_no in page_images:
                continue
            page_image_path = render_page_image(pdf_path, page_no, render_dir, dpi)
            page_images[page_no] = Image.open(page_image_path).convert("RGB")
            page_info = parse_page_info(pdf_path, page_no)
            page_infos[page_no] = QuestionPage(
                page_no=page_info.page_no,
                page_width=page_info.page_width,
                page_height=page_info.page_height,
                dpi_x=float(dpi),
                dpi_y=float(dpi),
            )

        for segment in result["segments"]:
            page_no = int(segment["page"])
            seg_bbox = segment["bbox"]
            local_bbox = segment.get("local_bbox", seg_bbox)
            src_image = page_images[page_no]
            src_page = page_infos[page_no]
            src_scale_x = src_page.dpi_x / 72.0 if src_page.dpi_x > 0 else 1.0
            src_scale_y = src_page.dpi_y / 72.0 if src_page.dpi_y > 0 else 1.0
            left = max(0, int(seg_bbox["x_min"] * src_scale_x))
            top = max(0, int(seg_bbox["y_min"] * src_scale_y))
            right = min(src_image.width, int(seg_bbox["x_max"] * src_scale_x))
            bottom = min(src_image.height, int(seg_bbox["y_max"] * src_scale_y))
            if right <= left or bottom <= top:
                continue
            crop = src_image.crop((left, top, right, bottom))
            dst_x = int(float(local_bbox["x_min"]) * base_scale_x)
            dst_y = int(float(local_bbox["y_min"]) * base_scale_y)
            image.paste(crop, (dst_x, dst_y))

        scale_x = image.width / page_width if page_width > 0 else 1.0
        scale_y = image.height / page_height if page_height > 0 else 1.0

        draw = ImageDraw.Draw(image)
        for idx, band in enumerate(result[band_key], start=1):
            bbox = band["bbox"]
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
                f"{idx}:{band['kind']}",
                fill="red",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)


def draw_band_overlay_on_image(image_path: Path, result: dict, output_path: Path, *, band_key: str = "merged_bands") -> None:
    image = Image.open(image_path).convert("RGB")
    page_width = float(result.get("page_width", image.width))
    page_height = float(result.get("page_height", image.height))
    scale_x = image.width / page_width if page_width > 0 else 1.0
    scale_y = image.height / page_height if page_height > 0 else 1.0

    draw = ImageDraw.Draw(image)
    for idx, band in enumerate(result[band_key], start=1):
        bbox = band["bbox"]
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
            f"{idx}:{band['kind']}",
            fill="red",
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="独立执行单题分块")
    parser.add_argument(
        "input",
        help=(
            "输入路径。"
            "有 --question-id 时为原始考卷 PDF；"
            "无 --question-id 时为单页 PDF 或单张图片。"
        ),
    )
    parser.add_argument(
        "--out",
        default="tmp/question_bands",
        help="输出目录，默认 tmp/question_bands",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="页面渲染 DPI，默认 180",
    )
    parser.add_argument(
        "--text-source",
        choices=("pdf", "surya", "hybrid"),
        default="surya",
        help="单题分块当前按 Surya 检测结果工作；pdf/hybrid 选项仅为兼容保留。",
    )
    parser.add_argument(
        "--question-id",
        help=(
            "题目标识，例如 p001_q10。"
            "提供时 input 应为原始考卷 PDF；"
            "省略时 input 直接作为单页 PDF 或图片处理。"
        ),
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"输入不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    is_image_input = input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

    if args.question_id:
        # Use ColumnQuestionSplitter to crop the question from the exam PDF.
        # Local import to avoid circular dependency.
        from split_columns_questions import ColumnQuestionSplitter

        question_id = args.question_id
        with ColumnQuestionSplitter(input_path, dpi=args.dpi) as splitter:
            question_img = splitter.get_question_image(question_id)
            page_no = splitter._page_no_from_question_id(question_id)
            page_record = splitter.compute_columns_and_questions(page_no)

        question_record = next(
            (q for q in page_record["questions"] if q["question_id"] == question_id),
            None,
        )
        if question_record is None:
            raise SystemExit(f"question_id not found: {question_id}")

        # Save cropped question image for overlay rendering
        source_image_path = out_dir / f"{question_id}_source.png"
        question_img.save(str(source_image_path))

        result = split_single_image(source_image_path, text_source=args.text_source)
        result["question_id"] = question_record["question_id"]
        result["question_no"] = question_record["question_no"]

        output_base = out_dir / question_id
        overlay_input_path = source_image_path
        overlay_is_image = True
    else:
        if is_image_input:
            result = split_single_image(input_path, text_source=args.text_source)
        else:
            result = split_single_page_pdf(input_path, dpi=args.dpi, text_source=args.text_source)
        output_base = out_dir / input_path.stem
        overlay_input_path = input_path
        overlay_is_image = is_image_input

    json_path = output_base.with_name(f"{output_base.name}_merged_bands.json")
    bands_json_path = output_base.with_name(f"{output_base.name}_bands.json")
    overlay_path = output_base.with_name(f"{output_base.name}_overlay.png")
    bands_overlay_path = output_base.with_name(f"{output_base.name}_bands_overlay.png")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    bands_json_path.write_text(
        json.dumps(
            {
                "question_id": result["question_id"],
                "question_no": result["question_no"],
                "page_width": result["page_width"],
                "page_height": result["page_height"],
                "question_text_height": result.get("question_text_height", 0.0),
                "body_flow_left_stats": result.get("body_flow_left_stats", {}),
                "segments": result["segments"],
                "bands": result["bands"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if overlay_is_image:
        draw_band_overlay_on_image(overlay_input_path, result, bands_overlay_path, band_key="bands")
        draw_band_overlay_on_image(overlay_input_path, result, overlay_path, band_key="merged_bands")
    else:
        draw_band_overlay(overlay_input_path, result, bands_overlay_path, dpi=args.dpi, band_key="bands")
        draw_band_overlay(overlay_input_path, result, overlay_path, dpi=args.dpi, band_key="merged_bands")

    print(f"bands: {bands_json_path}")
    print(f"merged_bands: {json_path}")
    print(f"bands_overlay: {bands_overlay_path}")
    print(f"overlay: {overlay_path}")


if __name__ == "__main__":
    main()
