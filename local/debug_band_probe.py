#!/usr/bin/env python3
"""
单独调试某一道题的 band 切分。

默认跟主程序的标准流程一致：
- 用 PDF 文字层做版面/锚点
- 用 Surya detect 做行框
- 再做 band / gap / cluster 判定
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

import rough_split_questions as rs


def merge_detected_lines(lines: list[rs.Line]) -> list[dict]:
    ordered = sorted(lines, key=lambda line: ((line.y_min + line.y_max) / 2.0, line.x_min))
    merged: list[dict] = []
    for line in ordered:
        line_mid = (line.y_min + line.y_max) / 2.0
        line_height = max(1.0, line.y_max - line.y_min)
        attached = False
        for item in reversed(merged):
            item_mid = (item["y_min"] + item["y_max"]) / 2.0
            vertical_overlap = rs.overlap_length(item["y_min"], item["y_max"], line.y_min, line.y_max)
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


def expand_line_bands(line_bands: list[dict], page_top: float, page_bottom: float, pad_pdf: float) -> list[dict]:
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


def classify_text_line(line_band: dict, column: rs.Column) -> str:
    raise RuntimeError("use rs.classify_text_line_band with image context")


def classify_gap_band(
    image: Image.Image,
    column: rs.Column,
    y_min: float,
    y_max: float,
    scale_x: float,
    scale_y: float,
    prev_band: dict | None = None,
) -> str:
    return rs.classify_gap_band_kind(image, column, y_min, y_max, scale_x, scale_y, prev_band=prev_band)


def merge_classified_bands(bands: list[dict]) -> list[dict]:
    core_kinds = {"body", "table", "visual_gap"}
    spacer_kinds = {"empty_gap", "line_gap", "table_gap", "label"}

    def boundary_connected(upper: dict, lower: dict) -> bool:
        return bool(upper.get("connect_down") and lower.get("connect_up"))

    def item_member_indices(item: dict) -> list[int]:
        return list(item.get("member_indices", [item["index"]]))

    def item_member_kinds(item: dict) -> list[str]:
        return list(item.get("member_kinds", [item["kind"]]))

    def item_text(item: dict) -> str:
        return item.get("text", "")

    def item_semantic_area(item: dict) -> int:
        return int(item.get("semantic_area", 0))

    def merge_items(group: list[dict], kind: str) -> dict:
        text_parts = [item.get("text", "") for item in group if item.get("text")]
        return {
            "kind": kind,
            "index": group[0]["index"],
            "band_type": group[0].get("band_type", "text"),
            "member_indices": [idx for item in group for idx in item_member_indices(item)],
            "member_kinds": [k for item in group for k in item_member_kinds(item)],
            "bbox": {
                "x_min": group[0]["bbox"]["x_min"],
                "y_min": min(item["bbox"]["y_min"] for item in group),
                "x_max": group[0]["bbox"]["x_max"],
                "y_max": max(item["bbox"]["y_max"] for item in group),
            },
            "text": "\n".join(part for item in group for part in [item_text(item)] if part),
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


def line_to_json(line: rs.Line) -> dict:
    return {
        "text": line.text,
        "x_min": line.x_min,
        "y_min": line.y_min,
        "x_max": line.x_max,
        "y_max": line.y_max,
    }


def band_to_json_ready(band: dict) -> dict:
    data = {k: v for k, v in band.items() if k != "line_band"}
    line_band = band.get("line_band")
    if isinstance(line_band, dict):
        data["line_band"] = {
            "text": line_band.get("text", ""),
            "x_min": line_band.get("x_min"),
            "y_min": line_band.get("y_min"),
            "x_max": line_band.get("x_max"),
            "y_max": line_band.get("y_max"),
            "lines": [line_to_json(line) for line in line_band.get("lines", [])],
        }
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="单题 band 调试")
    parser.add_argument("pdf", help="PDF 路径")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--question", default="9")
    parser.add_argument("--question-end", default=None, help="可选，结束题号；用于观察相邻多题区域")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--out", default="tmp/debug_band_probe")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = rs.analyze_page_layout(pdf_path, args.page)
    image_path = rs.render_page_image(pdf_path, args.page, out_dir, args.dpi)
    page_image = Image.open(image_path).convert("RGB")
    scale_x = page_image.width / layout.page_width
    scale_y = page_image.height / layout.page_height
    pad_pdf = 2.0 / scale_y

    scan_lines = rs.load_surya_lines({args.page: image_path}, {args.page: layout})[args.page]
    page_scan_lines = list(scan_lines) if scan_lines is not None else layout.lines

    anchors_by_column: dict[int, list[rs.Anchor]] = {column.index: [] for column in layout.columns}
    sections_by_column: dict[int, list[rs.Section]] = {column.index: [] for column in layout.columns}
    for anchor in layout.anchors:
        column = rs.assign_column(anchor.x_min, layout.columns)
        if column is not None:
            anchors_by_column[column.index].append(anchor)
    for section in layout.sections:
        column = rs.assign_column(section.x_min, layout.columns)
        if column is not None:
            sections_by_column[column.index].append(section)

    column_vertical_bounds = rs.compute_column_vertical_bounds_with_gutters(
        layout.columns,
        page_image,
        page_scan_lines,
        layout.footer_top,
        anchors_by_column,
        scale_x,
        scale_y,
    )
    column_blocks_by_index: dict[int, list[dict]] = {
        column.index: rs.build_column_blocks(
            args.page,
            column,
            page_image,
            layout.lines,
            page_scan_lines,
            column_vertical_bounds[column.index][0],
            column_vertical_bounds[column.index][1],
            layout.footer_top,
            scale_x,
            scale_y,
        )
        for column in layout.columns
    }
    first_record_top_floor_by_column: dict[int, float] = {}
    anchors_sorted_by_column: dict[int, list[rs.Anchor]] = {
        column.index: sorted(anchors_by_column.get(column.index, []), key=lambda item: item.y_min)
        for column in layout.columns
    }

    for column_idx in range(1, len(layout.columns)):
        column = layout.columns[column_idx]
        column_anchors = anchors_sorted_by_column.get(column.index, [])
        if not column_anchors:
            continue

        first_anchor = column_anchors[0]
        column_top, _ = column_vertical_bounds[column.index]
        pre_anchor_limit = max(column_top, first_anchor.y_min - 8.0)
        continuation_bottom = pre_anchor_limit
        section_lines_before_anchor = [
            section
            for section in sorted(sections_by_column.get(column.index, []), key=lambda item: item.y_min)
            if 20.0 <= section.y_min < pre_anchor_limit
        ]
        if section_lines_before_anchor:
            continuation_bottom = max(20.0, section_lines_before_anchor[0].y_min - 4.0)

        pre_anchor_lines = rs.lines_in_rect(
            layout.lines,
            column.x_min,
            column.x_max,
            column_top,
            continuation_bottom,
        )
        if not pre_anchor_lines or len(pre_anchor_lines) < 2:
            continue

        moved_blocks = [
            block
            for block in column_blocks_by_index.get(column.index, [])
            if block["bbox"]["y_min"] < continuation_bottom
        ]
        if not moved_blocks:
            continue

        column_blocks_by_index[column.index] = [
            block
            for block in column_blocks_by_index.get(column.index, [])
            if block["bbox"]["y_min"] >= continuation_bottom
        ]
        first_record_top_floor_by_column[column.index] = max(
            first_record_top_floor_by_column.get(column.index, column_top),
            max(block["bbox"]["y_max"] for block in moved_blocks),
        )

    start_q = str(int(args.question))
    end_q = str(int(args.question_end)) if args.question_end is not None else start_q
    anchor = next(anchor for anchor in layout.anchors if anchor.question_no == start_q)
    column = rs.assign_column(anchor.x_min, layout.columns)
    if column is None:
        raise RuntimeError("question column not found")
    column_anchors = anchors_sorted_by_column.get(column.index, [])
    question_blank_regions = [
        rs.find_question_blank_region_from_anchor(
            page_image,
            column,
            item.y_min,
            column_vertical_bounds[column.index][0],
            scale_x,
            scale_y,
        )
        for item in column_anchors
    ]
    question_blank_tops = [region[0] for region in question_blank_regions]
    question_tops = [region[1] for region in question_blank_regions]
    start_idx = next(idx for idx, item in enumerate(column_anchors) if item.question_no == start_q)
    end_anchor = next(
        anchor_item
        for anchor_item in layout.anchors
        if anchor_item.question_no == end_q and rs.assign_column(anchor_item.x_min, layout.columns) == column
    )
    end_idx = next(idx for idx, item in enumerate(column_anchors) if item.question_no == end_q)
    next_anchor = column_anchors[end_idx + 1] if end_idx + 1 < len(column_anchors) else None
    column_top, column_bottom = column_vertical_bounds[column.index]
    top = question_tops[start_idx]
    if start_idx == 0 and column.index in first_record_top_floor_by_column:
        top = max(top, first_record_top_floor_by_column[column.index])
    bottom = column_bottom if next_anchor is None else max(top + 0.1, question_blank_tops[end_idx + 1] - 0.6)

    region_lines = [
        line
        for line in rs.lines_in_rect(scan_lines, column.x_min, column.x_max, top, max(top, bottom - 0.01))
        if line.y_max >= anchor.y_min - 1.0
    ]
    text_lines = expand_line_bands(merge_detected_lines(region_lines), top, bottom, pad_pdf)

    bands = rs.build_structural_bands(
        text_lines,
        page_image,
        column,
        top,
        bottom,
        scale_x,
        scale_y,
    )
    bands = rs.classify_bands_in_order(bands, page_image, column, scale_x, scale_y)
    merged_bands = merge_classified_bands(bands)

    crop_left = int(column.x_min * scale_x)
    crop_top = int(top * scale_y)
    crop_right = int(column.x_max * scale_x)
    crop_bottom = int(bottom * scale_y)
    crop = page_image.crop((crop_left, crop_top, crop_right, crop_bottom))
    draw = ImageDraw.Draw(crop)
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
        x1 = int((bbox["x_min"] - column.x_min) * scale_x)
        y1 = int((bbox["y_min"] - top) * scale_y)
        x2 = int((bbox["x_max"] - column.x_min) * scale_x)
        y2 = int((bbox["y_max"] - top) * scale_y)
        draw.rectangle((x1, y1, x2, y2), outline=color_map.get(band["kind"], "blue"), width=3)
        draw.text((4, max(0, y1 + 2)), f'{band["index"]}:{band["kind"]}', fill=color_map.get(band["kind"], "blue"))

    merged = page_image.crop((crop_left, crop_top, crop_right, crop_bottom))
    merged_draw = ImageDraw.Draw(merged)
    merged_colors = {
        "body": "green",
        "label": "orange",
        "table": "blue",
        "empty_gap": "gray",
        "line_gap": "purple",
        "visual_gap": "red",
        "table_gap": "blue",
    }
    for idx, item in enumerate(merged_bands, 1):
        bbox = item["bbox"]
        x1 = int((bbox["x_min"] - column.x_min) * scale_x)
        y1 = int((bbox["y_min"] - top) * scale_y)
        x2 = int((bbox["x_max"] - column.x_min) * scale_x)
        y2 = int((bbox["y_max"] - top) * scale_y)
        color = merged_colors.get(item["kind"], "blue")
        merged_draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        merged_draw.text((4, max(0, y1 + 2)), f'{idx}:{item["kind"]}', fill=color)

    suffix = f"q{int(start_q):02d}" if start_q == end_q else f"q{int(start_q):02d}_q{int(end_q):02d}"
    json_path = out_dir / f"page_{args.page:03d}_{suffix}_bands.json"
    img_path = out_dir / f"page_{args.page:03d}_{suffix}_bands.png"
    merged_json_path = out_dir / f"page_{args.page:03d}_{suffix}_merged_bands.json"
    merged_img_path = out_dir / f"page_{args.page:03d}_{suffix}_merged_bands.png"
    bands_dir = out_dir / f"page_{args.page:03d}_{suffix}_band_crops"
    bands_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"bands": [band_to_json_ready(band) for band in bands]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    merged_json_path.write_text(json.dumps({"bands": merged_bands}, ensure_ascii=False, indent=2), encoding="utf-8")
    crop.save(img_path)
    merged.save(merged_img_path)

    bands_export: list[dict] = []
    for band in bands:
        bbox = band["bbox"]
        left, top, right, bottom = rs.bbox_to_px(bbox, scale_x, scale_y)
        band_crop = page_image.crop((left, top, right, bottom)).convert("RGB")
        band_name = f"band_{band['index']:02d}_{band['kind']}.png"
        band_path = bands_dir / band_name
        band_crop.save(band_path)
        dark_pixels = None
        if band["band_type"] == "gap":
            dark = rs.get_clean_dark_crop(page_image, bbox, scale_x, scale_y)
            if dark is not None:
                dark_pixels = int(dark.sum())
        bands_export.append(
            {
                "index": band["index"],
                "kind": band["kind"],
                "band_type": band["band_type"],
                "path": str(band_path),
                "dark_pixels": dark_pixels,
            }
        )
    (out_dir / f"page_{args.page:03d}_{suffix}_band_crops.json").write_text(
        json.dumps({"bands": bands_export}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"bands_json: {json_path}")
    print(f"bands_image: {img_path}")
    print(f"merged_bands_json: {merged_json_path}")
    print(f"merged_bands_image: {merged_img_path}")
    for band in bands:
        print(
            f'{band["index"]:02d} {band["band_type"]:>4} {band["kind"]:<11} '
            f'up={int(band["connect_up"])} down={int(band["connect_down"])} '
            f'{band["bbox"]["y_min"]:.2f}-{band["bbox"]["y_max"]:.2f} {band["text"]}'
        )
    print("--- merged bands ---")
    for idx, item in enumerate(merged_bands, 1):
        bbox = item["bbox"]
        print(
            f'{idx:02d} {item["kind"]:<11} {bbox["y_min"]:.2f}-{bbox["y_max"]:.2f} '
            f'members={item["member_indices"]} {item["text"]}'
        )


if __name__ == "__main__":
    main()
