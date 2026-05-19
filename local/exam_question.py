#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from exam_paper_parser import ExamPaper, PixelRect


@dataclass(frozen=True)
class Band:
    row: PixelRow
    type: str
    is_gap: bool
    connect_up: bool = False
    connect_down: bool = False


@dataclass(frozen=True)
class PixelRow:
    top: int
    bottom: int


@dataclass(frozen=True)
class TextBox:
    text: str
    rect: PixelRect


@dataclass(frozen=True)
class SplitResult:
    image: Image.Image
    text_blocks: list[TextBox]
    split_bands: list[Band]
    typed_bands: list[Band]
    merged_bands: list[Band]
    text_rows: list[PixelRow]


@dataclass(frozen=True)
class ConnectedComponent:
    label: int
    left: int
    top: int
    width: int
    height: int
    area: int
    centroid_x: float
    centroid_y: float


@dataclass(frozen=True)
class ConnectedComponentsResult:
    dark: np.ndarray | None
    masked_dark: np.ndarray | None
    num_labels: int
    labels: np.ndarray | None
    stats: np.ndarray | None
    centroids: np.ndarray | None
    components: list[ConnectedComponent]


class BinaryImageContext:
    """
    题目级连通区域缓存。

    当前所有计算都按像素单位处理：
    - `dark_image` 是像素级二值图
    - `text_boxes` 里的 rect 也是像素坐标
    - `find_connected_components()` 的 `y_min/y_max` 也按像素解释
    """

    def __init__(
        self,
        dark_image: np.ndarray,
        text_boxes: list[TextBox],
        *,
        text_mask_pad_px: int = 1,
    ) -> None:
        self._dark_image = dark_image.astype(np.uint8)
        self.text_boxes = list(text_boxes)
        self.text_pad_px = int(text_mask_pad_px)
        self._cache: dict[tuple[int, int, bool], ConnectedComponentsResult] = {}

    @property
    def height(self) -> int:
        return self._dark_image.shape[0]

    @property
    def width(self) -> int:
        return self._dark_image.shape[1]

    @property
    def dark_image(self) -> np.ndarray:
        return self._dark_image

    def find_connected_components(
        self,
        y_min: int,
        y_max: int,
        mask_text: bool,
    ) -> ConnectedComponentsResult:
        cache_key = (y_min, y_max, bool(mask_text))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        height, width = self.dark_image.shape
        top = max(0, y_min)
        bottom = min(height, y_max)
        if bottom - top <= 2:
            result = ConnectedComponentsResult(
                dark=None,
                masked_dark=None,
                num_labels=0,
                labels=None,
                stats=None,
                centroids=None,
                components=[],
            )
            self._cache[cache_key] = result
            return result

        dark = self.dark_image[top:bottom, :]
        masked = dark.copy()
        crop_height, crop_width = masked.shape[:2]
        if crop_width <= 0 or crop_height <= 0:
            result = ConnectedComponentsResult(
                dark=dark.astype(bool),
                masked_dark=masked.astype(bool),
                num_labels=0,
                labels=None,
                stats=None,
                centroids=None,
                components=[],
            )
            self._cache[cache_key] = result
            return result

        if mask_text:
            for line in self.text_boxes:
                x0 = max(0, line.rect.left - self.text_pad_px)
                x1 = min(crop_width, line.rect.right + self.text_pad_px)
                y0 = max(0, line.rect.top - top - self.text_pad_px)
                y1 = min(crop_height, line.rect.bottom - top + self.text_pad_px)
                if x1 <= x0 or y1 <= y0:
                    continue
                masked[y0:y1, x0:x1] = 0

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(masked.astype(np.uint8), connectivity=8)
        components: list[ConnectedComponent] = []
        for label_id in range(1, num_labels):
            components.append(
                ConnectedComponent(
                    label=int(label_id),
                    left=int(stats[label_id, cv2.CC_STAT_LEFT]),
                    top=int(stats[label_id, cv2.CC_STAT_TOP]),
                    width=int(stats[label_id, cv2.CC_STAT_WIDTH]),
                    height=int(stats[label_id, cv2.CC_STAT_HEIGHT]),
                    area=int(stats[label_id, cv2.CC_STAT_AREA]),
                    centroid_x=float(centroids[label_id][0]),
                    centroid_y=float(centroids[label_id][1]),
                )
            )

        result = ConnectedComponentsResult(
            dark=dark.astype(bool),
            masked_dark=masked.astype(bool),
            num_labels=int(num_labels),
            labels=labels,
            stats=stats,
            centroids=centroids,
            components=components,
        )
        self._cache[cache_key] = result
        return result

    def find_text_boxes(self, rect: PixelRect, coverage: float = 1.0) -> list[TextBox]:
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
        if right <= left or bottom <= top:
            return []

        threshold = max(0.0, min(1.0, float(coverage)))
        matched: list[TextBox] = []
        for box in self.text_boxes:
            box_left = int(box.rect.left)
            box_top = int(box.rect.top)
            box_right = int(box.rect.right)
            box_bottom = int(box.rect.bottom)
            overlap_width = _overlap_length(left, right, box_left, box_right)
            if overlap_width <= 0:
                continue
            overlap_height = _overlap_length(top, bottom, box_top, box_bottom)
            if overlap_height <= 0:
                continue
            box_area = max(0, box_right - box_left) * max(0, box_bottom - box_top)
            if box_area <= 0:
                continue
            overlap_area = overlap_width * overlap_height
            if overlap_area / box_area < threshold:
                continue
            matched.append(box)

        return matched

    def find_text_boxes_in_row(self, row: PixelRow, coverage: float = 1.0) -> list[TextBox]:
        return self.find_text_boxes(PixelRect(0, row.top, self.width, row.bottom), coverage=coverage)


def _overlap_length(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def draw_rows_in_image(
    image: Image.Image,
    rows: list[tuple[PixelRow, str, str]],
) -> Image.Image:
    return draw_rects_in_image(image,
                               [(PixelRect(0, r[0].top, image.width, r[0].bottom), r[1], r[2]) for r in rows])


def draw_rects_in_image(
    image: Image.Image,
    rects: list[tuple[PixelRect, str, str]],
) -> Image.Image:
    marked = image.copy().convert("RGB")
    draw = ImageDraw.Draw(marked)
    font = ImageFont.load_default()
    for rect, comment1, comment2 in rects:
        draw.rectangle(
            [rect.left, rect.top, rect.right, rect.bottom],
            outline="red",
            width=2,
        )
        if comment1:
            left_top = (rect.left + 2, rect.top + 2)
            draw.text(
                left_top,
                comment1,
                fill="red",
                font=font,
            )
        if comment2:
            text_bbox = draw.textbbox((0, 0), comment2, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            right = rect.right - 2
            bottom = rect.bottom - 2
            x = max(rect.left + 2, right - text_width)
            y = max(rect.top + 2, bottom - text_height)
            draw.text(
                (x, y),
                comment2,
                fill="red",
                font=font,
            )
    return marked


def _text_boxes_to_rows(boxes: list[TextBox],
                        padding: int = 2) -> list[PixelRow]:
    ordered = sorted(
        boxes,
        key=lambda b: (
            (b.rect.top + b.rect.bottom) / 2.0,
            b.rect.left,
        ),
    )
    merged: list[PixelRow] = []
    for box in ordered:
        box_mid = (box.rect.top + box.rect.bottom) / 2.0
        assert box.rect.bottom > box.rect.top
        box_height = box.rect.bottom - box.rect.top
        attached = False
        if merged:
            last_row = merged[-1]
            assert isinstance(last_row, PixelRow)
            row_mid = (last_row.top + last_row.bottom) / 2.0
            row_height = last_row.bottom - last_row.top
            vertical_overlap = _overlap_length(
                last_row.top,
                last_row.bottom,
                box.rect.top,
                box.rect.bottom,
            )
            if (
                abs(row_mid - box_mid) <= box_height * 0.5
                or vertical_overlap >= min(box_height, row_height) * 0.5
            ):
                merged[-1] = PixelRow(min(last_row.top, box.rect.top),
                                      max(last_row.bottom, box.rect.bottom))
                attached = True

        if not attached:
            merged.append(PixelRow(box.rect.top, box.rect.bottom))

    pad = max(0, int(padding))
    result: list[PixelRow] = []
    for row in merged:
        top = max(0, row.top - pad)
        bottom = row.bottom + pad
        current = PixelRow(top, bottom)
        current_height = current.bottom - current.top

        # Keep the rows non-overlapping by dropping the shorter row in an
        # overlapping pair instead of shrinking either boundary.
        while result and current.top < result[-1].bottom:
            last = result[-1]
            last_height = last.bottom - last.top
            if current_height > last_height:
                result.pop()
                continue
            break

        if result and current.top < result[-1].bottom:
            continue
        if current.top >= current.bottom:
            continue
        result.append(current)

    return result


def _split_to_raw_bands(
    context: BinaryImageContext,
    text_rows: list[PixelRow],
) -> list[Band]:
    height, width = context.dark_image.shape
    bands: list[Band] = []
    prev_bottom = 0

    for row in text_rows:
        if row.top > prev_bottom:
            bands.append(
                Band(
                    row=PixelRow(prev_bottom, row.top),
                    type="",
                    is_gap=True,
                )
            )

        bands.append(
            Band(
                row=PixelRow(row.top, row.bottom),
                type="",
                is_gap=False,
            )
        )
        prev_bottom = row.bottom

    if prev_bottom < height:
        bands.append(
            Band(
                row=PixelRow(prev_bottom, height),
                type="",
                is_gap=True,
            )
        )

    return bands


def _estimate_text_height(context: BinaryImageContext,
                          row: PixelRow) -> int:
    boxes: list[TextBox] = context.find_text_boxes_in_row(row)
    keep_count = max(1, (len(boxes) + 1) // 2)
    kept = sorted(boxes, key=lambda box: (box.rect.right - box.rect.left), reverse=True)[:keep_count]
    return max(box.rect.bottom - box.rect.top for box in kept)


def _compute_text_band_left(
    context: BinaryImageContext,
    band: Band,
) -> int:
    info = context.find_connected_components(band.row.top, band.row.bottom, False)
    components = [
        c
        for c in (info.components or [])
        if c.width * c.height >= 13 and c.width >= 2 and c.height >= 2
    ]
    if components:
        return min(comp.left for comp in components)
    else:
        boxes: list[TextBox] = context.find_text_boxes_in_row(band.row)
        return min(box.rect.left for box in boxes)


def _compute_body_flow_stats(context: BinaryImageContext,
                             raw_bands: list[Band],
                             text_height: int) -> tuple[list[int], list[list[int]]]:
    assert text_height > 0
    max_chars = 5
    left_buckets: list[list[int]] = [[] for _ in range(max_chars)]

    sample_count = 0
    for band in raw_bands:
        if band.is_gap:
            continue
        current_left = _compute_text_band_left(
            context,
            band,
        )
        bucket = int(float(current_left) / float(text_height))
        if 0 <= bucket < max_chars:
            left_buckets[bucket].append(current_left)
            sample_count += 1

    if sample_count == 0:
        left_mark: list[int] = []
    else:
        max_count = max(len(bkt) for bkt in left_buckets)
        left_mark = [min(bkt) for bkt in left_buckets if len(bkt) == max_count][:2]

    return left_mark, left_buckets


def filter_small_components(
    info: ConnectedComponentsResult,
    min_area: int = 10,
    min_width: int = 3,
    min_height: int = 3,
) -> list[ConnectedComponent]:
    assert info
    matched: list[ConnectedComponent] = []
    for comp in info.components:
        if (
            comp.width * comp.height >= min_area
            and int(comp.width) >= min_width
            and int(comp.height) >= min_height
        ):
            matched.append(comp)
    return matched


def _is_table_text_row(
    band: Band,
    boxes: list[TextBox],
    info: ConnectedComponentsResult,
) -> bool:
    masked_dark = info.masked_dark
    components = info.components or []
    if masked_dark is None or not isinstance(masked_dark, np.ndarray):
        return False

    left_candidates = [c for c in components
                       if c.left + c.width < min(box.rect.left for box in boxes)]
    right_candidates = [c for c in components
                        if c.left >= max(box.rect.right for box in boxes)]

    if not left_candidates or not right_candidates:
        return False

    left_component = min(left_candidates, key=lambda comp: (comp.left, -comp.height))
    right_component = max(right_candidates, key=lambda comp: (comp.left + comp.width, comp.height))

    min_height = max(3, int((band.row.bottom - band.row.top) * 0.8))
    return (left_component.height >= min_height
            and right_component.height >= min_height)


def _classify_text_band_in_sequence(
    context: BinaryImageContext,
    band: Band,
) -> str:
    """Classify one text band as `table`, `label`, or `body`.

    Rules, in order:
    1. If the band matches the table-row heuristic, return `table`.
    2. If no text boxes are detected in the band, return `body`.
    3. Compute the text span and text area from the detected boxes.
    4. If the band is vertically connected to its neighbors and the text is
       not clearly body-like (`left <= 18%` of the context width and
       `text width >= 30%` of the context width), return `label`.
    5. If the meaningful masked connected-component area is larger than the
       raw text area, return `label`.
    6. If there is at least one sufficiently large connected component to the
       left of the text, return `label`.
    7. Otherwise return `body`.

    Notes:
    - `body_like_left` and `body_like_width` are coarse heuristics for the
      usual body-text shape.
    - The left-component check uses a small margin so nearby glyph noise does
      not count as a label cue.
    """
    boxes = context.find_text_boxes_in_row(band.row)
    info = context.find_connected_components(band.row.top, band.row.bottom, True)
    assert boxes, f"no text in {band}"
    # 1) 先识别表格行：左右两侧都有足够高的结构图元时，直接判为 table。
    if _is_table_text_row(band, boxes, info):
        return "table"

    # 3) 提取文字框的整体左边界、右边界和文字面积，作为正文/标签的基础特征。
    text_x_min = min(line.rect.left for line in boxes)
    text_x_max = max(line.rect.right for line in boxes)
    text_area = 0
    for box in boxes:
        text_area += max(0, box.rect.right-box.rect.left) * max(0, box.rect.bottom-box.rect.top)
    components = filter_small_components(info, 13, 2, 2)

    component_area = sum(comp.width * comp.height for comp in components)

    # 4) 正文通常更靠左且更宽；如果不满足这个形态，又带有上下连通关系，就更像 label。
    body_like_left = (text_x_min / context.width) <= 0.18
    # body_like_width = ((text_x_max - text_x_min) / context.width) >= 0.3

    if not body_like_left:
        return "label"
    # 5) 如果遮字后的结构面积比文字面积还大，说明这段更像含图元的标签而不是纯正文。
    if component_area > text_area:
        return "label"

    # 6) 文字左侧如果还有独立的足够大图元，通常也是 label。
    margin = 4
    left_components = [c for c in filter_small_components(info, 23, 5, 5)
                       if c.left + c.width + margin < text_x_min]
    if len(left_components) >= 1:
        return "label"
    return "body"


def _compute_gap_band_parts(
    context: BinaryImageContext,
    row: PixelRow,
    verbose: bool = False
) -> list[PixelRow]:
    info = context.find_connected_components(row.top, row.bottom, False)
    masked_dark = info.masked_dark
    height, _ = masked_dark.shape
    if height < 6:
        return []

    components = filter_small_components(info, min_area=6)
    if not components:
        return []

    if verbose:
        print(components)

    intervals = sorted(
        ((comp.top, comp.top + comp.height) for comp in components),
        key=lambda item: (item[0], item[1]),
    )
    merged: list[PixelRow] = []
    for start, end in intervals:
        if not merged:
            merged.append(PixelRow(start, end))
            continue
        last = merged[-1]
        if start <= last.bottom:
            merged[-1] = PixelRow(last.top, max(last.bottom, end))
        else:
            merged.append(PixelRow(start, end))

    if verbose:
        print(merged)

    return merged


def _split_gap_bands(context: BinaryImageContext,
                     raw_bands: list[Band],
                     text_height: int = 12,
                     ) -> list[Band]:
    refined: list[Band] = []
    for idx in range(len(raw_bands)):
        band = raw_bands[idx]
        if not band.is_gap or band.row.bottom - band.row.top < text_height/2:
            refined.append(band)
            continue
        assert idx < 1 or not raw_bands[idx - 1].is_gap
        assert idx >= len(raw_bands) - 1 or not raw_bands[idx + 1].is_gap

        parts = _compute_gap_band_parts(
            context,
            band.row,
            #    verbose=band.row.top == 85
        )
        if len(parts) <= 1:
            refined.append(band)
            continue

        # _compute_gap_band_parts() returns segments relative to the gap band,
        # so shift them back to absolute page coordinates before splitting.
        parts = [
            PixelRow(
                band.row.top + part.top,
                band.row.top + part.bottom,
            )
            for part in parts
        ]

        first = parts[0]
        last = parts[-1]
        assert first.bottom < last.top
        split_points = [band.row.top]
        if first.top > band.row.top:
            split_points.append(first.top)
        split_points.append(first.bottom)
        split_points.append(last.top)
        if last.bottom < band.row.bottom:
            split_points.append(last.bottom)
        split_points.append(band.row.bottom)

        assert len(split_points) > 2, split_points

        rows: list[PixelRow] = [PixelRow(split_points[idx], split_points[idx + 1])
                                for idx in range(len(split_points) - 1)]

        refined.append(Band(
            row=rows[0],
            type=band.type,
            is_gap=True,
            connect_up=band.connect_up,
            connect_down=False,
        ))
        for row in rows[1:-1]:
            refined.append(Band(
                row=row,
                type=band.type,
                is_gap=True,
                connect_up=False,
                connect_down=False,
            ))
        # at least 2 rows
        refined.append(Band(
            row=rows[-1],
            type=band.type,
            is_gap=True,
            connect_up=False,
            connect_down=band.connect_down,
        ))

    return refined


def _apply_body_correction(context: BinaryImageContext,
                           bands: list[Band],
                           text_height: int,
                           body_flow_left: list[int]) -> list[Band]:
    assert text_height > 0
    corrected: list[Band] = []
    left_mark = max(body_flow_left)
    right_shift_threshold = 3 * text_height
    for band in bands:
        if band.type != "body":
            corrected.append(band)
            continue
        current_left = _compute_text_band_left(context, band)
        positive_deltas = current_left - left_mark if current_left > left_mark else 0
        if positive_deltas >= right_shift_threshold:
            corrected.append(Band(row=band.row,
                                  is_gap=band.is_gap,
                                  type="label",
                                  connect_up=band.connect_up,
                                  connect_down=band.connect_down,
                                  ))
        else:
            corrected.append(band)
    return corrected


def _is_single_line_gap(info: ConnectedComponentsResult,
                        text_height: int = 10,
                        ) -> bool:
    components = filter_small_components(info)
    if not components:
        return False
    for comp in components:
        if comp.height > text_height*0.16:
            return False
        if comp.top > text_height*0.25:
            return False
    return True


def _classify_gap_band_in_sequence(
    context: BinaryImageContext,
    band: Band,
    text_height: int,
) -> str:
    info = context.find_connected_components(band.row.top, band.row.bottom, False)
    masked_dark = info.masked_dark
    if masked_dark is None or not isinstance(masked_dark, np.ndarray):
        return "empty_gap"
    band_area_px = int(masked_dark.size)

    components = filter_small_components(info)
    semantic_area = sum(comp.width * comp.height for comp in components)
    is_line_gap = _is_single_line_gap(info)
    height_delta = band.row.bottom - band.row.top
    thresh = max(20, int(band_area_px * 0.002))
    if is_line_gap:
        return "line_gap"
    if height_delta <= text_height*0.2 or semantic_area <= thresh:
        return "empty_gap"
    return "visual_gap"


def _classify_bands_in_order(
    context: BinaryImageContext,
    raw_bands: list[Band],
    text_height: int,
) -> tuple[list[Band], list[int]]:
    body_flow_left, _ = _compute_body_flow_stats(context, raw_bands, text_height)
    # 对所有gap根据空白做进一步分割
    split_bands = _split_gap_bands(context, raw_bands, text_height)
    classified = []
    for band in split_bands:
        if not band.is_gap:
            band_type = _classify_text_band_in_sequence(context, band)
        else:
            band_type = _classify_gap_band_in_sequence(context, band, text_height)
        classified.append(Band(row=band.row,
                               type=band_type,
                               connect_up=band.connect_up,
                               connect_down=band.connect_down,
                               is_gap=band.is_gap))
    classified = _apply_body_correction(context, classified, text_height, body_flow_left)
    # corrected = assign_pairwise_band_connectivity(corrected, detector, scale_y)
    return classified, body_flow_left


def _assign_band_connectivity(
    context: BinaryImageContext,
    bands: list[Band],
) -> list[Band]:
    connected = bands.copy()
    if len(connected) < 2:
        return connected

    boundary_pad = 3
    for idx in range(len(connected) - 1):
        upper = connected[idx]
        lower = connected[idx + 1]
        assert upper.row.bottom == lower.row.top
        boundary_y = lower.row.top
        window_y_min = max(upper.row.top, boundary_y - boundary_pad)
        window_y_max = min(lower.row.bottom, boundary_y + boundary_pad)
        if window_y_max <= window_y_min:
            continue
        if has_spanning_component(context, window_y_min, window_y_max):
            connected[idx] = Band(
                row=upper.row,
                type=upper.type,
                is_gap=upper.is_gap,
                connect_up=upper.connect_up,
                connect_down=True,
            )
            connected[idx + 1] = Band(
                row=lower.row,
                type=lower.type,
                is_gap=lower.is_gap,
                connect_up=True,
                connect_down=lower.connect_down,
            )

    return connected


def has_spanning_component(
    context: BinaryImageContext,
    top: int,
    bottom: int,
    min_width: int = 2,
) -> bool:
    assert context
    assert min_width > 0
    assert 0 <= top < bottom <= context.height

    components_info = context.find_connected_components(top, bottom, False)
    dark = components_info.masked_dark
    if dark is None or not dark.any():
        return False

    num_labels = int(components_info.num_labels or 0)
    labels = components_info.labels
    stats = components_info.stats
    if num_labels <= 1:
        return False
    if labels is None or stats is None:
        return False

    top_labels = set(int(v) for v in labels[0, :] if v != 0)
    bottom_labels = set(int(v) for v in labels[-1, :] if v != 0)
    spanning = top_labels & bottom_labels
    if not spanning:
        return False

    for label_id in spanning:
        width_i = int(stats[label_id, cv2.CC_STAT_WIDTH])
        if width_i >= min_width:
            return True
    return False


def _merge_sibling_bands(group: list[Band], band_type: str) -> Band:
    return Band(row=PixelRow(top=min(band.row.top for band in group),
                             bottom=max(band.row.bottom for band in group)),
                is_gap=False,
                type=band_type,
                connect_up=group[0].connect_up,
                connect_down=group[-1].connect_down,
                )


def _converge_connectivity(context: BinaryImageContext,
                           bands: list[Band],
                           trace_log: dict) -> list[Band]:
    """先按 band 之间的连接关系做第一轮收敛合并。

    这个阶段的目标不是最终定型，而是把“明显属于同一结构块”的
    相邻 band 先合并掉，减少后续 core/spacer 收敛时面对的碎片数。

    处理规则大致如下：
    - 相邻同类型的 ``body / table / label`` 直接合并。
    - 当前项是 ``label``、后一个项是 gap，且这个 gap 没有向上连接时，
      尝试把它们合并，并用 gap 的连通域形态决定最终保留 ``label``
      还是保留 gap kind。
    - 当前项是 gap、后一个项是 ``label``，且这个 gap 没有向下连接时，
      同样按形态决定合并后的类型。
    - 当前项是 ``body / table``、后一个项是带向上连接的 gap 时，优先
      把这个 gap 吸收到前面的 core band。
    - 当前项是带向下连接的 gap、后一个项是 ``body / table`` 时，优先
      把这个 gap 吸收到后面的 core band。

    这个阶段会反复迭代，直到一轮内不再发生合并，并且会把每一轮的
    中间结果写入 `trace_log`，方便调试 merge 过程。
    """
    def text_shadow_width(band: Band) -> int:
        boxes = context.find_text_boxes_in_row(band.row)
        return sum(max(0, box.rect.right - box.rect.left) for box in boxes)

    def gap_shadow_width(band: Band) -> int:
        info = context.find_connected_components(band.row.top, band.row.bottom, False)
        components = filter_small_components(info)

        occupied = [False] * max(0, int(context.width))
        for comp in components:
            left = max(0, int(comp.left))
            right = min(len(occupied), int(comp.left + comp.width))
            for x in range(left, right):
                occupied[x] = True
        shadow_width = sum(1 for flag in occupied if flag)
        return shadow_width

    def select_label_gap_type(label_band: Band, gap_band: Band) -> str:
        assert label_band.type == "label" and gap_band.is_gap
        label_band_height = label_band.row.bottom - label_band.row.top
        label_width = text_shadow_width(label_band)
        gap_band_height = gap_band.row.bottom - gap_band.row.top
        gap_width = gap_shadow_width(gap_band)
        if gap_width > label_width or gap_band_height > label_band_height:
            return gap_band.type
        else:
            return label_band.type

    merged_bands = bands
    round_idx = 0
    changed = True
    while changed:
        changed = False
        modified: list[Band] = []
        idx = 0
        while idx < len(merged_bands):
            current = merged_bands[idx]
            if idx + 1 >= len(merged_bands):
                modified.append(current)
                break

            next_band = merged_bands[idx + 1]
            merge_to_type = ""
            if (
                current.type in {"body", "table", "label"}
                and next_band.type == current.type
            ):
                merge_to_type = current.type
            elif (
                    current.type == "label"
                    and next_band.is_gap
                    and next_band.connect_up
            ):
                merge_to_type = select_label_gap_type(current, next_band)
            elif (
                    current.is_gap
                    and next_band.type == "label"
                    and current.connect_down
            ):
                merge_to_type = select_label_gap_type(next_band, current)
            elif (
                    current.type in {"body", "table"}
                    and next_band.is_gap
                    and next_band.connect_up
            ):
                merge_to_type = current.type
            elif (
                    current.is_gap
                    and next_band.type in {"body", "table"}
                    and current.connect_down
            ):
                merge_to_type = next_band.type

            if merge_to_type:
                modified.append(_merge_sibling_bands([current, next_band], merge_to_type))
                idx += 2
                changed = True
            else:
                modified.append(current)
                idx += 1
        merged_bands = modified
        round_idx += 1
        trace_log[f"connectivity:round_{round_idx}"] = merged_bands
    return merged_bands


def _converge_core_spacer(
                          bands: list[Band],
                          trace_log: dict
                          ) -> list[Band]:
    core_kinds = {"body", "table", "visual_gap"}
    spacer_kinds = {"empty_gap", "line_gap", "label"}

    merged_bands = bands
    round_idx = 0
    trace_log["core_spacer:start"] = merged_bands
    changed = True
    while changed:
        changed = False
        modified: list[Band] = []
        idx = 0
        while idx < len(merged_bands):
            current = merged_bands[idx]
            if idx + 1 >= len(merged_bands):
                modified.append(current)
                break

            next_band = merged_bands[idx + 1]
            prev_band = merged_bands[idx - 1] if idx > 0 else None
            merge_to_type = ""
            if (
                idx == 0
                and current.type in spacer_kinds
                and next_band.type in core_kinds
            ):
                merge_to_type = next_band.type
            elif (
                prev_band
                and prev_band.type in {"body", "table"}
                and current.type in spacer_kinds
                and next_band.type == prev_band.type
            ):
                merge_to_type = next_band.type
            elif (
                idx == len(merged_bands) - 2
                and current.type in core_kinds
                and next_band.type in spacer_kinds
            ):
                merge_to_type = current.type
            elif (
                current.type in core_kinds
                and next_band.type == current.type
            ):
                merge_to_type = current.type

            if merge_to_type:
                modified.append(_merge_sibling_bands([current, next_band], merge_to_type))
                idx += 2
                changed = True
            else:
                modified.append(merged_bands[idx])
                idx += 1
        round_idx += 1
        trace_log[f"connectivity:round_{round_idx}"] = modified
        merged_bands = modified
    return merged_bands


def _merge_typed_bands(context: BinaryImageContext,
                       connected_bands: list[Band]):
    """对已分类、已带连接信息的 band 序列做最终合并与规整。

    这个阶段不再做“类型识别”，只做“结构收敛”：
    1. 先把 `line_gap` 预处理成更容易向上吸收的形态。
    2. 按连接关系做第一轮合并，把明显属于同一结构块的相邻 band 先并掉。
    3. 再做 core/spacer 收敛，吸收开头、结尾和中间夹层里的 spacer。
    4. 单独处理 `line_gap`，因为它通常表示细小的行内空隙，需要特殊吸收。
    5. 把连续的 `empty_gap / label` 压成更稳定的 spacer 结构。
    6. 最后把剩余 spacer 尽量吸收到 `table / visual_gap`，得到更紧凑的结果。

    返回值：
    - `absorbed_visual_table`：最终合并后的 band 序列
    - `merge_trace`：每个阶段的中间结果，便于调试 merge 过程
    """
    merge_trace: dict = {}

    def record_trace(stage: str, items: list[Band]) -> None:
        merge_trace[stage] = items

    prepared_bands: list[Band] = []
    for band in connected_bands:
        # `line_gap` 先标记为向上可连接，后续更容易被 core/spacer 流程吸收。
        if band.type == "line_gap":
            prepared_bands.append(Band(row=band.row,
                                       is_gap=band.is_gap,
                                       type=band.type,
                                       connect_up=True,
                                       connect_down=band.connect_down
                                       ))
        else:
            prepared_bands.append(band)
    record_trace("prepared", prepared_bands)

    bands_s1 = _converge_connectivity(context, prepared_bands, merge_trace)
    record_trace("after_connectivity", bands_s1)

    # 第一轮 core/spacer 收敛：吃掉首尾 spacer、同类 core、以及中间夹着 spacer
    # 的同类 core 结构。
    bands_s2 = _converge_core_spacer(bands_s1, merge_trace)
    record_trace("after_core_spacer", bands_s2)

    # `line_gap` 常常表示很短的行间空隙，若它前面已经是 spacer，
    # 就先把它并进前一个 spacer，再走一轮 core/spacer 收敛。
    bands_s3: list[Band] = []
    idx = 0
    line_gap_changed = False
    line_absorb_prev_types = {"empty_gap", "label"}
    while idx < len(bands_s2):
        current = bands_s2[idx]
        if current.type == "line_gap" and bands_s3 and bands_s3[-1].type in line_absorb_prev_types:
            prev_band = bands_s3.pop()
            bands_s3.append(_merge_sibling_bands([prev_band, current], prev_band.type))
            line_gap_changed = True
        else:
            bands_s3.append(current)
        idx += 1
    if line_gap_changed:
        record_trace("after_line_gap_absorb", bands_s3)
        bands_s3 = _converge_core_spacer(bands_s3, merge_trace)
        record_trace("after_line_gap_core_spacer", bands_s3)

    # 连续的 empty_gap / label 会被压缩成更稳定的 spacer 结构。
    bands_s4: list[Band] = []
    idx = 0
    spacer_only_types = {"empty_gap", "label"}
    spacer_collapsed = False
    while idx < len(bands_s3):
        current = bands_s3[idx]
        if current.type not in spacer_only_types:
            bands_s4.append(bands_s3[idx])
            idx += 1
            continue
        group = [current]
        idx += 1
        while idx < len(bands_s3) and bands_s3[idx].type in spacer_only_types:
            group.append(bands_s3[idx])
            idx += 1
        if len(group) > 1 and any(item.type == "label" for item in group):
            bands_s4.append(_merge_sibling_bands(group, "label"))
            spacer_collapsed = True
        else:
            bands_s4.extend(group)
    if spacer_collapsed:
        record_trace("after_label_spacer_collapse", bands_s4)
        bands_s4 = _converge_core_spacer(bands_s4, merge_trace)
        record_trace("after_label_core_spacer", bands_s4)

    # 最后尝试把 spacer 吸收到相邻的 table / visual_gap 中，
    # 让最终序列更紧凑，减少孤立 spacer 的数量。
    final_spacer_types = {"empty_gap", "label"}
    absorb_target_types = {"table", "visual_gap"}
    bands_s5: list[Band] = []
    idx = 0
    final_absorb_changed = False
    while idx < len(bands_s4):
        current = bands_s4[idx]
        if current.type not in final_spacer_types:
            bands_s5.append(current)
            idx += 1
            continue
        prev_band = bands_s5[-1] if bands_s5 else None
        next_band = bands_s4[idx + 1] if idx + 1 < len(bands_s4) else None
        if prev_band is not None and prev_band.type in absorb_target_types:
            bands_s5[-1] = _merge_sibling_bands([prev_band, current], prev_band.type)
            final_absorb_changed = True
            idx += 1
            continue
        if next_band is not None and next_band.type in absorb_target_types:
            bands_s5.append(_merge_sibling_bands([current, next_band], next_band.type))
            final_absorb_changed = True
            idx += 2
            continue
        bands_s5.append(current)
        idx += 1
    if final_absorb_changed:
        record_trace("after_final_visual_table_absorb", bands_s5)
        bands_s5 = _converge_core_spacer(bands_s5, merge_trace)
        record_trace("after_final_core_spacer", bands_s5)

    return bands_s5, merge_trace


def split_question_bands(
    binary_image: Image,
) -> SplitResult:
    """Split one question image into semantic bands.

    The pipeline is:
    1. Detect text boxes on the binary question image.
    2. Convert the text boxes into non-overlapping text rows.
       Each row is a coarse y-range that covers one visual text line or one
       text cluster.
    3. Build a binary-image context that can query masked connected components
       and text boxes for any band range.
    4. Split the question vertically into raw bands:
       - every text row becomes a text band
       - the intervals between adjacent text rows become gap bands
    5. Estimate a representative text height from the first text row.
    6. Classify bands in order:
       - text bands are classified as ``table``, ``label``, or ``body``
         using textbox geometry, connected components, and left-side layout
         heuristics
       - gap bands are classified as ``empty_gap``, ``line_gap``, or
         ``visual_gap``
       - gap bands may be split again when their internal connected components
         show multiple content fragments
       - body bands may be corrected to label bands when the body flow
         baseline suggests they are too far to the right
    7. Recompute pairwise connectivity flags for the classified bands.
    8. Merge adjacent typed bands into larger semantic bands.
       The merge stage is the final normalization pass: it absorbs obvious
       duplicates, folds spacer bands into neighboring core bands when the
       connectivity says they belong together, and records the merge trace for
       debugging.

    Returns:
    - ``split_bands``: the raw text/gap partition before typing
    - ``typed_bands``: the per-band classification result after band splitting
      and body correction
    - ``merged_bands``: the merged final band sequence
    - ``text_blocks``: the detected text boxes
    - ``text_rows``: the row ranges derived from the text boxes

    If no text boxes are detected, the whole image is returned as a single
    ``visual_gap`` band.
    """
    text_boxes = _detect_text_boxes(binary_image)
    if len(text_boxes) > 0:
        text_rows = _text_boxes_to_rows(text_boxes)
        assert len(text_rows) > 0
        context = BinaryImageContext((255 - np.asarray(binary_image)), text_boxes)
        split_bands = _split_to_raw_bands(context, text_rows)
        text_height = _estimate_text_height(context, text_rows[0])
        typed_bands, _ = _classify_bands_in_order(context,
                                                  split_bands,
                                                  text_height)
        typed_bands = _assign_band_connectivity(context, typed_bands)
        merged_bands, merge_trace = _merge_typed_bands(context, typed_bands)

        return SplitResult(
            image=binary_image,
            split_bands=split_bands,
            text_blocks=text_boxes,
            text_rows=text_rows,
            typed_bands=typed_bands,
            merged_bands=merged_bands,
        )
    else:
        full_band = Band(
            row=PixelRow(0, int(binary_image.height)),
            type="visual_gap",
            is_gap=True,
        )
        return SplitResult(
            image=binary_image,
            split_bands=[full_band],
            typed_bands=[full_band],
            merged_bands=[full_band],
            text_blocks=text_boxes,
            text_rows=[],
        )


def split_question_bands_in_exam(
    exam_paper: ExamPaper,
    page_no: int,
    question_no: int,
) -> SplitResult:
    return split_question_bands(exam_paper.create_question_binary_image(page_no, question_no, padding=2))


def _detect_text_boxes(binary_image: Image.Image) -> list[TextBox]:
    """Use Surya to detect text lines in a binary PIL image.

    The input is expected to be a binarized image object, typically the
    question image returned by ``ExamPaper.create_question_binary_image``.
    The function returns pixel-space line boxes with placeholder text labels.
    """
    image_array = np.asarray(binary_image)
    if image_array.size == 0:
        return []

    gray = image_array.astype(np.uint8)

    if not np.any(gray == 0):
        return []

    def _select_surya_device() -> str:
        configured = os.environ.get("TORCH_DEVICE")
        if configured and configured.lower() not in {"mps", "auto"}:
            return configured
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
        except (ImportError, AttributeError, RuntimeError):
            pass
        return "cpu"

    os.environ["TORCH_DEVICE"] = _select_surya_device()
    from surya.detection import DetectionPredictor

    predictor = DetectionPredictor()
    results = predictor([binary_image.convert("RGB")])
    if not results:
        return []

    boxes: list[TextBox] = []
    height, width = gray.shape[:2]
    for idx, detected_box in enumerate(results[0].bboxes):
        left = max(0, min(width, int(np.floor(detected_box.bbox[0]))))
        top = max(0, min(height, int(np.floor(detected_box.bbox[1]))))
        right = max(0, min(width, int(np.ceil(detected_box.bbox[2]))))
        bottom = max(0, min(height, int(np.ceil(detected_box.bbox[3]))))
        if right <= left or bottom <= top:
            continue
        boxes.append(
            TextBox(
                text=f"TXT_{idx + 1}",
                rect=PixelRect(left=left, top=top, right=right, bottom=bottom),
            )
        )

    return boxes


def _validate_binary_image(image: Image.Image, source: Path | None = None) -> None:
    """Reject images that are not strictly binary (0/255 or mode '1')."""
    if image.mode == "1":
        return

    gray = np.asarray(image.convert("L"))
    if gray.size == 0:
        return

    unique_values = np.unique(gray)
    if unique_values.size == 0:
        return

    if unique_values.size == 1 and int(unique_values[0]) in {0, 255}:
        return

    if unique_values.size == 2 and set(int(v) for v in unique_values.tolist()) <= {0, 255}:
        return

    location = f" ({source})" if source is not None else ""
    raise ValueError(f"input image is not binary{location}; expected only 0/255 pixels")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打印指定试卷题目的 part 列表")
    parser.add_argument("--dir", dest="work_dir", type=Path, help="试卷工作目录")
    parser.add_argument("--page", dest="page_no", type=int, help="页号")
    parser.add_argument("--question", dest="question_no", type=int, help="题号")
    parser.add_argument(
        "-i",
        "--image",
        dest="image_path",
        type=Path,
        help="直接输入题目图片文件，使用后不需要 --dir/--page/--question",
    )
    parser.add_argument(
        "-g",
        "--generate-image",
        action="store_true",
        help="生成题目图片并保存为 q<page_no>_<question_no>.png",
    )
    parser.add_argument(
        "-b",
        "--generate-binary-image",
        action="store_true",
        help="生成题目二值图并保存为 q<page_no>_<question_no>_binary.png",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("exam-data"),
        help="图片输出目录，默认 exam-data",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.image_path is not None:
        if args.work_dir is not None or args.page_no is not None or args.question_no is not None:
            parser.error("-i cannot be used with --dir/--page/--question")
    else:
        if args.work_dir is None or args.page_no is None or args.question_no is None:
            parser.error("either -i or --dir/--page/--question must be provided")

    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        if args.image_path is not None:
            with Image.open(args.image_path) as opened_image:
                _validate_binary_image(opened_image, args.image_path)
                question_image = opened_image.convert("L").copy()
            result = split_question_bands(question_image)
            image_source = question_image
            exam_paper = None
        else:
            exam_paper = ExamPaper(args.work_dir)
            result = split_question_bands_in_exam(exam_paper, args.page_no, args.question_no)
            image_source = None
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    for band in result.merged_bands:
        print(band)

    try:
        saved_path: Path | None = None
        saved_binary_path: Path | None = None
        if args.generate_image:
            if exam_paper is not None:
                raw_image = exam_paper.create_question_image(args.page_no, args.question_no, padding=2)
                image_name = f"q{args.page_no}_{args.question_no}.png"
            else:
                raw_image = image_source.copy()
                image_name = f"{args.image_path.stem}.png"
            image = draw_rows_in_image(
                raw_image,
                [
                    (band.row, band.type, f"U{int(band.connect_up)} D{int(band.connect_down)}")
                    for band in result.merged_bands
                ],
            )

            output_dir = args.out
            output_dir.mkdir(parents=True, exist_ok=True)
            saved_path = output_dir / image_name
            image.save(saved_path)
        if args.generate_binary_image:
            if exam_paper is not None:
                binary_image = exam_paper.create_question_binary_image(args.page_no, args.question_no, padding=2)
                binary_name = f"q{args.page_no}_{args.question_no}_binary.png"
            else:
                binary_image = image_source.copy()
                binary_name = f"{args.image_path.stem}_binary.png"
            image = draw_rows_in_image(
                binary_image,
                [
                    (band.row, band.type, f"U{int(band.connect_up)} D{int(band.connect_down)}")
                    for band in result.merged_bands
                ],
            )
            output_dir = args.out
            output_dir.mkdir(parents=True, exist_ok=True)
            saved_binary_path = output_dir / binary_name
            image.save(saved_binary_path)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if saved_path is not None:
        print(f"图片已保存到: {saved_path}")
    if saved_binary_path is not None:
        print(f"二值图已保存到: {saved_binary_path}")


if __name__ == "__main__":
    main()
