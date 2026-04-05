#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
import re
import shutil
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET
from statistics import mean
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_DPI = 180
SOFT_BINARY_MAX_THRESHOLD = 205
PDF_POINTS_PER_INCH = 72.0


@dataclass(frozen=True)
class Rect:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class PixelRect:
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class Line:
    text: str
    rect: Rect


@dataclass(frozen=True)
class Anchor:
    question_no: str
    text: str
    rect: Rect


@dataclass(frozen=True)
class QuestionPart:
    anchor_text: str
    rect: Rect
    column: int
    index_in_page: int


@dataclass(frozen=True)
class Question:
    question_no: int
    part_ids: list[int]
    text: str


@dataclass(frozen=True)
class Column:
    index: int
    rect: Rect
    start_x: float


@dataclass(frozen=True)
class PageLayout:
    question_parts: list[QuestionPart]
    columns: list[Column]
    is_exam_page: bool
    reasons: list[str]


@dataclass(frozen=True)
class DocumentInfo:
    original_file_name: str
    page_count: int


@dataclass(frozen=True)
class PageInfo:
    page_no: int
    width: float
    height: float
    pixel_width: int
    pixel_height: int
    lines: list[Line]
    layout: PageLayout
    questions: list[Question] = field(default_factory=list)


def draw_rects_on_image(
    image: Image.Image,
    rects: Sequence[Rect],
    page_width: float,
    page_height: float,
) -> Image.Image:
    marked = image.copy().convert("RGB")
    draw = ImageDraw.Draw(marked)
    font = ImageFont.load_default()
    scale_x = image.width / page_width if page_width > 0 else 1.0
    scale_y = image.height / page_height if page_height > 0 else 1.0
    for rect in rects:
        left = int(round(rect.x_min * scale_x))
        top = int(round(rect.y_min * scale_y))
        right = int(round(rect.x_max * scale_x))
        bottom = int(round(rect.y_max * scale_y))
        draw.rectangle(
            (
                left,
                top,
                right,
                bottom,
            ),
            outline="red",
            width=3,
        )
        draw.text((left + 3, top + 3), f"{rect.x_min:.0f},{rect.y_min:.0f}", fill="red", font=font)
        draw.text((right - 60, bottom - 16), f"{rect.x_max:.0f},{rect.y_max:.0f}", fill="red", font=font)
    return marked


def pdf_rect_to_pixel_rect(rect: Rect, scale_x: float, scale_y: float) -> PixelRect:
    return PixelRect(
        left=max(0, int(np.floor(rect.x_min * scale_x))),
        top=max(0, int(np.floor(rect.y_min * scale_y))),
        right=max(0, int(np.ceil(rect.x_max * scale_x))),
        bottom=max(0, int(np.ceil(rect.y_max * scale_y))),
    )


def pixel_rect_to_pdf_rect(rect: PixelRect, scale_x: float, scale_y: float) -> Rect:
    return Rect(
        x_min=float(rect.left / scale_x) if scale_x > 0 else float(rect.left),
        y_min=float(rect.top / scale_y) if scale_y > 0 else float(rect.top),
        x_max=float(rect.right / scale_x) if scale_x > 0 else float(rect.right),
        y_max=float(rect.bottom / scale_y) if scale_y > 0 else float(rect.bottom),
    )


def largest_true_rectangle(
    mask: np.ndarray,
    min_width: int = 0,
    min_height: int = 0,
) -> PixelRect | None:
    # Classic maximal-rectangle-in-binary-matrix algorithm.
    # Treat each row as the base of a histogram, then use a monotonic stack
    # to find the largest rectangle for that row in O(width).
    if mask.size == 0:
        return None

    height, width = mask.shape[:2]
    heights = [0] * width
    best_area = 0
    best_rect: PixelRect | None = None

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
                rect_width = right - left
                rect_height = h
                if rect_width < min_width or rect_height < min_height:
                    continue
                area = rect_height * rect_width
                if area > best_area:
                    best_area = area
                    best_rect = PixelRect(
                        left=left,
                        top=row - h + 1,
                        right=right,
                        bottom=row + 1,
                    )
            stack.append(idx)

    return best_rect


def find_largest_blank_rect_in_rect(
    binary_image: np.ndarray,
    rect: PixelRect,
    min_width: int = 0,
    min_height: int = 0,
) -> PixelRect | None:
    # Work entirely in pixel coordinates: crop the requested window and search
    # the white/background pixels directly.
    if binary_image.size == 0:
        return None

    height, width = binary_image.shape[:2]
    left = max(0, rect.left)
    top = max(0, rect.top)
    right = min(width, rect.right)
    bottom = min(height, rect.bottom)
    if right <= left or bottom <= top:
        return None

    crop = binary_image[top:bottom, left:right].astype(bool)
    blank_mask = crop
    rect_pixels = largest_true_rectangle(
        blank_mask,
        min_width=max(0, min_width),
        min_height=max(0, min_height),
    )
    if rect_pixels is None:
        print(
            f"find_largest_blank_rect_in_rect input={rect} min_width={min_width} min_height={min_height} output=None"
        )
        return None

    result = PixelRect(
        left=left + rect_pixels.left,
        top=top + rect_pixels.top,
        right=left + rect_pixels.right,
        bottom=top + rect_pixels.bottom,
    )
    return result


def find_blank_y_intervals_in_rect(
    binary_image: np.ndarray,
    rect: PixelRect,
) -> list[PixelRect]:
    # Project the cropped image onto the y axis: a row is blank when the
    # entire row inside the requested x-range is background/white.
    if binary_image.size == 0:
        return []

    height, width = binary_image.shape[:2]
    left = max(0, rect.left)
    top = max(0, rect.top)
    right = min(width, rect.right)
    bottom = min(height, rect.bottom)
    if right <= left or bottom <= top:
        return []

    crop = binary_image[top:bottom, left:right].astype(bool)
    blank_rows = np.all(crop, axis=1)

    intervals: list[PixelRect] = []
    start: int | None = None
    for offset, is_blank in enumerate(blank_rows):
        if bool(is_blank):
            if start is None:
                start = offset
            continue
        if start is not None:
            intervals.append(
                PixelRect(
                    left=left,
                    top=top + start,
                    right=right,
                    bottom=top + offset,
                )
            )
            start = None

    if start is not None:
        intervals.append(
            PixelRect(
                left=left,
                top=top + start,
                right=right,
                bottom=top + len(blank_rows),
            )
        )

    return intervals


class ExamPaper:
    def __init__(self, work_dir: Path, dpi: int = DEFAULT_DPI):
        self.work_dir = Path(work_dir)
        self._dpi = dpi
        self._document_info: DocumentInfo | None = self._load_document_info()
        self._page_infos: dict[int, PageInfo] = {}
        self._raw_images: dict[int, Image.Image] = {}
        self._binary_images: dict[int, np.ndarray] = {}

    @property
    def document_path(self) -> Path:
        return self.work_dir / "paper.pdf"

    @property
    def debug_dir(self) -> Path:
        return self.work_dir / "debug"

    @property
    def dpi(self) -> int:
        return self._dpi

    def _document_info_path(self) -> Path:
        return self.work_dir / "document_info.json"

    def get_page_dir(self, page_no: int) -> Path:
        return self.work_dir / f"p{page_no}"

    def _page_manifest_path(self, page_no: int) -> Path:
        return self.get_page_dir(page_no) / "manifest.json"

    @property
    def scale_x(self) -> float:
        return self._dpi / PDF_POINTS_PER_INCH

    @property
    def scale_y(self) -> float:
        return self._dpi / PDF_POINTS_PER_INCH

    def pdf_rect_to_pixel_rect(self, rect: Rect) -> PixelRect:
        return pdf_rect_to_pixel_rect(rect, self.scale_x, self.scale_y)

    def pixel_rect_to_pdf_rect(self, rect: PixelRect) -> Rect:
        return pixel_rect_to_pdf_rect(rect, self.scale_x, self.scale_y)

    def save_document(self, info: DocumentInfo) -> Path:
        assert info and info.original_file_name
        source_pdf = Path(info.original_file_name)
        self.document_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_pdf, self.document_path)
        self._document_info = info
        self._document_info_path().write_text(
            json.dumps(asdict(info), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.document_path

    def save_page_binary_image(self, page_no: int, image: np.ndarray) -> Path:
        assert 0 < page_no <= self._document_info.page_count
        path = self._binary_image_path(page_no)
        path.parent.mkdir(parents=True, exist_ok=True)
        binary = Image.fromarray((image * 255).astype(np.uint8), mode="L")
        binary.save(path)
        self._binary_images[page_no] = image.copy()
        return path

    def save_page_raw_image(self, page_no: int, image: Image.Image) -> Path:
        assert 0 < page_no <= self._document_info.page_count
        raw_path = self._raw_image_path(page_no)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(raw_path)
        self._raw_images[page_no] = image.copy()
        return raw_path

    def _raw_image_path(self, page_no: int) -> Path:
        return self.get_page_dir(page_no) / "raw.png"

    def _binary_image_path(self, page_no: int) -> Path:
        return self.get_page_dir(page_no) / "soft_binary.png"

    def _load_raw_images(self) -> dict[int, Image.Image]:
        raw_images: dict[int, Image.Image] = {}
        for page_dir in sorted(self.work_dir.glob("p*")):
            if not page_dir.is_dir():
                continue
            match = re.match(r"^p(\d+)$", page_dir.name)
            if not match:
                continue
            page_no = int(match.group(1))
            raw_path = page_dir / "raw.png"
            if not raw_path.exists():
                continue
            try:
                with Image.open(raw_path) as image:
                    raw_images[page_no] = image.copy()
            except OSError:
                continue
        return raw_images

    def _load_document_info(self) -> DocumentInfo | None:
        document_info_path = self._document_info_path()
        if document_info_path.exists():
            data = json.loads(document_info_path.read_text(encoding="utf-8"))
            return DocumentInfo(
                original_file_name=str(data["original_file_name"]),
                page_count=int(data["page_count"]),
            )
        if not self.document_path.exists():
            return None
        return DocumentInfo(
            original_file_name=self.document_path.name,
            page_count=get_total_pages(self.document_path),
        )

    @property
    def document_info(self) -> DocumentInfo | None:
        return self._document_info

    def _page_layout_from_dict(self, data: dict) -> PageLayout:
        return PageLayout(
            question_parts=[
                QuestionPart(
                    anchor_text=str(item["anchor_text"]),
                    rect=Rect(
                        x_min=float(item["rect"]["x_min"]),
                        y_min=float(item["rect"]["y_min"]),
                        x_max=float(item["rect"]["x_max"]),
                        y_max=float(item["rect"]["y_max"]),
                    ),
                    column=int(item["column"]),
                    index_in_page=int(item["index_in_page"]),
                )
                for item in data["question_parts"]
            ],
            columns=[
                Column(
                    index=int(item["index"]),
                    rect=Rect(
                        x_min=float(item["rect"]["x_min"]),
                        y_min=float(item["rect"]["y_min"]),
                        x_max=float(item["rect"]["x_max"]),
                        y_max=float(item["rect"]["y_max"]),
                    ),
                    start_x=float(item["start_x"]),
                )
                for item in data["columns"]
            ],
            is_exam_page=bool(data["is_exam_page"]),
            reasons=[str(item) for item in data["reasons"]],
        )

    def _page_info_from_dict(self, data: dict) -> PageInfo:
        questions = [
            Question(
                question_no=int(item["question_no"]),
                part_ids=[int(part_id) for part_id in item["part_ids"]],
                text=str(item["text"]),
            )
            for item in data["questions"]
        ]
        return PageInfo(
            page_no=int(data["page_no"]),
            width=float(data["width"]),
            height=float(data["height"]),
            pixel_width=int(data["pixel_width"]),
            pixel_height=int(data["pixel_height"]),
            lines=[
                Line(
                    text=str(item["text"]),
                    rect=Rect(
                        x_min=float(item["rect"]["x_min"]),
                        y_min=float(item["rect"]["y_min"]),
                        x_max=float(item["rect"]["x_max"]),
                        y_max=float(item["rect"]["y_max"]),
                    ),
                )
                for item in data["lines"]
            ],
            layout=self._page_layout_from_dict(data["layout"]),
            questions=questions,
        )

    def _load_page_layouts(self) -> dict[int, PageInfo]:
        page_infos: dict[int, PageInfo] = {}
        for page_dir in sorted(self.work_dir.glob("p*")):
            if not page_dir.is_dir():
                continue
            match = re.match(r"^p(\d+)$", page_dir.name)
            if not match:
                continue
            page_no = int(match.group(1))
            manifest_path = page_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            page_info = self._page_info_from_dict(data)
            page_infos[page_info.page_no] = page_info
        return page_infos

    def save_page_info(self, page_info: PageInfo) -> Path:
        self._page_infos[page_info.page_no] = page_info
        manifest_path = self._page_manifest_path(page_info.page_no)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(asdict(page_info), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest_path

    def get_page_info(self, page_no: int) -> PageInfo | None:
        page_info = self._page_infos.get(page_no)
        if page_info is not None:
            return page_info
        manifest_path = self.get_page_dir(page_no) / "manifest.json"
        if not manifest_path.exists():
            return None
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        page_info = self._page_info_from_dict(data)
        self._page_infos[page_no] = page_info
        return page_info

    def find_question_parts(self, page_no: int, question_no: int) -> list[QuestionPart]:
        page_info = self.get_page_info(page_no)
        if page_info is None:
            raise FileNotFoundError(f"page info not found for page {page_no}")

        question = self.get_question(page_no, question_no)

        parts_by_id = {
            part.index_in_page: part
            for part in page_info.layout.question_parts
        }
        parts: list[QuestionPart] = []
        for part_id in question.part_ids:
            part = parts_by_id.get(part_id)
            if part is None:
                raise KeyError(
                    f"question part not found: page={page_no}, question_no={question_no}, part_id={part_id}"
                )
            parts.append(part)

        return parts

    def get_question(self, page_no: int, question_no: int) -> Question:
        page_info = self.get_page_info(page_no)
        if page_info is None:
            raise FileNotFoundError(f"page info not found for page {page_no}")

        question_no_int = int(question_no)
        if question_no_int <= 0 or question_no_int > len(page_info.questions):
            raise KeyError(f"question not found: page={page_no}, question_no={question_no_int}")
        return page_info.questions[question_no_int - 1]

    def create_question_image(
        self,
        page_no: int,
        question_no: int,
        gap_pt: float = 4.0,
        padding: float = 0.0,
    ) -> Image.Image:
        parts = self.find_question_parts(page_no, question_no)
        if self.get_page_raw_image(page_no) is None:
            raise FileNotFoundError(f"raw page image not found for page {page_no}")

        gap_px = max(0, int(round(gap_pt * self.scale_y)))
        padding_pt = max(0.0, min(20.0, float(padding)))
        padding_px = max(0, int(round(padding_pt * self.scale_y)))
        crops: list[Image.Image] = []
        for part in parts:
            crop = self.get_page_raw_image(page_no, part.rect)
            if crop is None or crop.width <= 0 or crop.height <= 0:
                continue
            crops.append(crop)

        if not crops:
            raise RuntimeError(
                f"no parts could be cropped for page={page_no}, question_no={question_no}"
            )

        if len(crops) == 1:
            stitched = crops[0].copy()
        else:
            max_width = max(crop.width for crop in crops)
            total_height = sum(crop.height for crop in crops) + gap_px * (len(crops) - 1)
            stitched = Image.new("RGB", (max_width, total_height), "white")
            offset_y = 0
            for idx, crop in enumerate(crops):
                stitched.paste(crop, (0, offset_y))
                offset_y += crop.height
                if idx + 1 < len(crops):
                    offset_y += gap_px

        if padding_px <= 0:
            return stitched

        padded = Image.new(
            stitched.mode,
            (stitched.width + padding_px * 2, stitched.height + padding_px * 2),
            "white",
        )
        padded.paste(stitched, (padding_px, padding_px))
        return padded

    def create_question_binary_image(
        self,
        page_no: int,
        question_no: int,
        gap_pt: float = 4.0,
        padding: float = 0.0,
    ) -> Image.Image:
        parts = self.find_question_parts(page_no, question_no)
        if self.get_page_binary_image(page_no) is None:
            raise FileNotFoundError(f"binary page image not found for page {page_no}")

        gap_px = max(0, int(round(gap_pt * self.scale_y)))
        padding_pt = max(0.0, min(20.0, float(padding)))
        padding_px = max(0, int(round(padding_pt * self.scale_y)))
        crops: list[np.ndarray] = []
        for part in parts:
            crop = self.get_page_binary_image(page_no, part.rect)
            if crop is None or crop.size == 0:
                continue
            crops.append(crop)

        if not crops:
            raise RuntimeError(
                f"no parts could be cropped for page={page_no}, question_no={question_no}"
            )

        if len(crops) == 1:
            stitched = crops[0].copy()
        else:
            max_width = max(crop.shape[1] for crop in crops)
            total_height = sum(crop.shape[0] for crop in crops) + gap_px * (len(crops) - 1)
            stitched = np.ones((total_height, max_width), dtype=bool)
            offset_y = 0
            for idx, crop in enumerate(crops):
                height, width = crop.shape[:2]
                stitched[offset_y:offset_y + height, 0:width] = crop
                offset_y += height
                if idx + 1 < len(crops):
                    offset_y += gap_px

        if padding_px > 0:
            padded = np.ones(
                (stitched.shape[0] + padding_px * 2, stitched.shape[1] + padding_px * 2),
                dtype=bool,
            )
            padded[padding_px:padding_px + stitched.shape[0], padding_px:padding_px + stitched.shape[1]] = stitched
            stitched = padded

        return Image.fromarray(stitched.astype(np.uint8) * 255, mode="L")

    def save_debug_file(self, name: str, content: str | bytes) -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def get_page_binary_image(self, page_no: int, rect: Rect | None = None) -> np.ndarray | None:
        cached_binary = self._binary_images.get(page_no)
        if cached_binary is not None:
            binary = cached_binary.copy()
            if rect is None:
                return binary
            pixel_rect = self.pdf_rect_to_pixel_rect(rect)
            left = max(0, min(binary.shape[1], pixel_rect.left))
            top = max(0, min(binary.shape[0], pixel_rect.top))
            right = max(0, min(binary.shape[1], pixel_rect.right))
            bottom = max(0, min(binary.shape[0], pixel_rect.bottom))
            return binary[top:bottom, left:right].copy()
        binary_path = self._binary_image_path(page_no)
        if binary_path.exists():
            with Image.open(binary_path) as image:
                cached_binary = np.asarray(image.convert("L")) > 0
            self._binary_images[page_no] = cached_binary
            binary = cached_binary.copy()
            if rect is None:
                return binary
            pixel_rect = self.pdf_rect_to_pixel_rect(rect)
            left = max(0, min(binary.shape[1], pixel_rect.left))
            top = max(0, min(binary.shape[0], pixel_rect.top))
            right = max(0, min(binary.shape[1], pixel_rect.right))
            bottom = max(0, min(binary.shape[0], pixel_rect.bottom))
            return binary[top:bottom, left:right].copy()
        return None

    def get_page_raw_image(self, page_no: int, rect: Rect | None = None) -> Image.Image | None:
        cached_image = self._raw_images.get(page_no)
        if cached_image is not None:
            image = cached_image.copy()
            if rect is None:
                return image
            pixel_rect = self.pdf_rect_to_pixel_rect(rect)
            left = max(0, min(image.width, pixel_rect.left))
            top = max(0, min(image.height, pixel_rect.top))
            right = max(0, min(image.width, pixel_rect.right))
            bottom = max(0, min(image.height, pixel_rect.bottom))
            return image.crop((left, top, right, bottom)).copy()
        raw_path = self._raw_image_path(page_no)
        if raw_path.exists():
            with Image.open(raw_path) as image:
                cached_image = image.copy()
            self._raw_images[page_no] = cached_image
            image = cached_image.copy()
            if rect is None:
                return image
            pixel_rect = self.pdf_rect_to_pixel_rect(rect)
            left = max(0, min(image.width, pixel_rect.left))
            top = max(0, min(image.height, pixel_rect.top))
            right = max(0, min(image.width, pixel_rect.right))
            bottom = max(0, min(image.height, pixel_rect.bottom))
            return image.crop((left, top, right, bottom)).copy()
        return None

    def ready(self) -> bool:
        if not self._document_info:
            return False
        for page_no in range(1, self._document_info.page_count + 1):
            if not self.get_page_info(page_no):
                return False
        return True


def run_cmd(args: list[str]) -> str:
    proc = subprocess.run(args, check=True, capture_output=True, text=True)
    return proc.stdout


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def make_output_dir_name(pdf_path: Path) -> str:
    stem = pdf_path.stem.strip()
    if not stem:
        stem = "exam"

    # Keep the directory name filesystem-friendly and predictable.
    name = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("._")
    return name or "exam"


def create_output_dir(pdf_file: str) -> Path:
    pdf_path = Path(pdf_file)
    output_root = Path.cwd() / "exam-data"
    output_dir = output_root / make_output_dir_name(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
                rect=Rect(
                    x_min=float(elem.attrib["xMin"]),
                    y_min=float(elem.attrib["yMin"]),
                    x_max=float(elem.attrib["xMax"]),
                    y_max=float(elem.attrib["yMax"]),
                ),
            )
        )
    return page_width, page_height, lines


def find_question_anchors(lines: Iterable[Line], page_width: float) -> list[Anchor]:
    anchors: list[Anchor] = []
    for line in lines:
        if line.rect.y_min < 20.0:
            continue
        if line.rect.x_min < page_width * 0.03:
            continue
        question_no = extract_question_no(line.text)
        if question_no is None:
            continue
        if len(line.text) < 8:
            continue
        anchors.append(
            Anchor(
                question_no=str(question_no),
                text=line.text,
                rect=line.rect,
            )
        )
    return anchors


def extract_question_no(text: str) -> int | None:
    match = re.match(r"^\s*(\d{1,2})\s*[.．、](?!\d)", text)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def cluster_anchor_starts(anchors: Sequence[Anchor], page_width: float) -> list[float]:
    if not anchors:
        return []

    threshold = max(90.0, page_width * 0.08)
    starts = sorted(anchor.rect.x_min for anchor in anchors)
    clusters: list[list[float]] = [[starts[0]]]
    for start in starts[1:]:
        if abs(start - mean(clusters[-1])) <= threshold:
            clusters[-1].append(start)
        else:
            clusters.append([start])
    return [mean(cluster) for cluster in clusters]


def build_columns(column_starts: Sequence[float], page_width: float, page_height: float) -> list[Column]:
    if not column_starts:
        return []

    columns: list[Column] = []
    for index, start_x in enumerate(column_starts):
        x_min = start_x
        x_max = column_starts[index + 1] if index + 1 < len(column_starts) else page_width
        columns.append(
            Column(
                index=index,
                rect=Rect(x_min=x_min, y_min=0.0, x_max=x_max, y_max=page_height),
                start_x=start_x,
            )
        )
    return columns


def rect_intersection_area(a: Rect, b: Rect) -> float:
    x_min = max(a.x_min, b.x_min)
    y_min = max(a.y_min, b.y_min)
    x_max = min(a.x_max, b.x_max)
    y_max = min(a.y_max, b.y_max)
    if x_max <= x_min or y_max <= y_min:
        return 0.0
    return (x_max - x_min) * (y_max - y_min)


def rect_area(rect: Rect) -> float:
    if rect.x_max <= rect.x_min or rect.y_max <= rect.y_min:
        return 0.0
    return (rect.x_max - rect.x_min) * (rect.y_max - rect.y_min)


def lines_in_rect(
    lines: Iterable[Line],
    rect: Rect,
    min_overlap_ratio: float = 1.0,
) -> list[Line]:
    if min_overlap_ratio <= 0:
        return list(lines)

    threshold = max(0.0, min(1.0, float(min_overlap_ratio)))
    matched: list[Line] = []
    for line in lines:
        line_area = rect_area(line.rect)
        if line_area <= 0:
            continue
        overlap = rect_intersection_area(line.rect, rect)
        if overlap / line_area >= threshold:
            matched.append(line)
    return matched


def _estimate_text_metrics(lines: Sequence[Line], rect: Rect) -> tuple[float, float]:
    line_heights = [
        line.rect.y_max - line.rect.y_min
        for line in lines
        if line.rect.y_max > line.rect.y_min
    ]
    line_height = float(np.median(line_heights)) if line_heights else max(1.0, rect.y_max - rect.y_min)

    char_widths = [
        (line.rect.x_max - line.rect.x_min) / max(1, len(line.text.strip()))
        for line in lines
        if line.text.strip() and line.rect.x_max > line.rect.x_min
    ]
    char_width = float(np.median(char_widths)) if char_widths else max(1.0, line_height * 0.6)
    return max(1.0, line_height), max(0.5, char_width)


def _group_lines_by_rows(lines: Sequence[Line], line_height: float) -> list[list[Line]]:
    if not lines:
        return []

    ordered = sorted(lines, key=lambda line: (line.rect.y_min, line.rect.x_min, line.rect.y_max, line.rect.x_max))
    row_gap = max(1.0, line_height * 0.35)
    groups: list[list[Line]] = []
    current_group: list[Line] = [ordered[0]]
    current_bottom = ordered[0].rect.y_max

    for line in ordered[1:]:
        if line.rect.y_min <= current_bottom + row_gap:
            current_group.append(line)
            current_bottom = max(current_bottom, line.rect.y_max)
            continue
        groups.append(current_group)
        current_group = [line]
        current_bottom = line.rect.y_max

    groups.append(current_group)
    return groups


def _render_text_row(lines: Sequence[Line], rect: Rect, char_width: float) -> str:
    width_chars = max(1, int(round((rect.x_max - rect.x_min) / char_width)))
    buffer = [" "] * width_chars
    for line in sorted(lines, key=lambda item: (item.rect.x_min, item.rect.y_min, item.rect.x_max, item.rect.y_max)):
        start = int(round((line.rect.x_min - rect.x_min) / char_width))
        if start >= width_chars:
            continue
        start = max(0, start)
        text = line.text.rstrip()
        for offset, ch in enumerate(text):
            pos = start + offset
            if pos >= width_chars:
                break
            if buffer[pos] == " ":
                buffer[pos] = ch
    return "".join(buffer).rstrip()


def text_in_rect(
    lines: Iterable[Line],
    rect: Rect,
) -> str:
    matched = lines_in_rect(lines, rect, min_overlap_ratio=0.8)
    if not matched:
        return ""

    line_height, char_width = _estimate_text_metrics(matched, rect)
    rows = _group_lines_by_rows(matched, line_height)

    output_lines: list[str] = []
    previous_bottom: float | None = None
    for row in rows:
        row_top = min(line.rect.y_min for line in row)
        row_bottom = max(line.rect.y_max for line in row)
        if previous_bottom is not None:
            gap = row_top - previous_bottom
            blank_lines = max(0, int(round(gap / line_height)) - 1)
            output_lines.extend([""] * blank_lines)
        output_lines.append(_render_text_row(row, rect, char_width))
        previous_bottom = row_bottom

    return "\n".join(output_lines).rstrip()


def build_question_parts(
    columns: Sequence[Column],
    anchors_by_column: dict[int, list[Anchor]],
    lines: Sequence[Line],
) -> tuple[list[QuestionPart], list[Question]]:
    question_parts: list[QuestionPart] = []
    question_records: list[tuple[int, int]] = []
    index_in_page = 0
    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.rect.y_min)
        if column_anchors:
            first_anchor = column_anchors[0]
            top_gap = first_anchor.rect.y_min - column.rect.y_min
            anchor_height = first_anchor.rect.y_max - first_anchor.rect.y_min
            if top_gap >= anchor_height and top_gap > 0:
                question_parts.append(
                    QuestionPart(
                        anchor_text="",
                        rect=Rect(
                            x_min=column.rect.x_min,
                            y_min=column.rect.y_min,
                            x_max=column.rect.x_max,
                            y_max=first_anchor.rect.y_min,
                        ),
                        column=column.index,
                        index_in_page=index_in_page,
                    )
                )
                index_in_page += 1
        for index, anchor in enumerate(column_anchors):
            part_top = anchor.rect.y_min
            part_bottom = column.rect.y_max
            if index + 1 < len(column_anchors):
                part_bottom = min(part_bottom, column_anchors[index + 1].rect.y_min)
            if part_bottom <= part_top:
                continue
            question_parts.append(
                QuestionPart(
                    anchor_text=anchor.text,
                    rect=Rect(
                        x_min=column.rect.x_min,
                        y_min=part_top,
                        x_max=column.rect.x_max,
                        y_max=part_bottom,
                    ),
                    column=column.index,
                    index_in_page=index_in_page,
                )
            )
            question_records.append((column.index, index_in_page))
            index_in_page += 1

    question_parts_sorted = sorted(question_parts, key=lambda item: item.index_in_page)
    question_only_parts = [part for part in question_parts_sorted if part.anchor_text.strip()]
    parts_by_id = {part.index_in_page: part for part in question_parts_sorted}
    questions: list[Question] = []
    for index_in_page, (column_index, primary_part_id) in enumerate(question_records):
        part_ids = [primary_part_id]
        current_column_questions = [
            part
            for part in question_only_parts
            if part.column == column_index
        ]
        if current_column_questions and primary_part_id == max(
            part.index_in_page for part in current_column_questions
        ):
            next_blank_part = next(
                (
                    part
                    for part in question_parts_sorted
                    if part.column == column_index + 1 and not part.anchor_text.strip()
                ),
                None,
                )
            if next_blank_part is not None:
                part_ids.append(next_blank_part.index_in_page)
        rendered_parts: list[str] = []
        for part_id in part_ids:
            part = parts_by_id.get(part_id)
            if part is None:
                continue
            rendered = text_in_rect(lines, part.rect).rstrip()
            if rendered.strip():
                rendered_parts.append(rendered)
        questions.append(
            Question(
                question_no=index_in_page + 1,
                part_ids=part_ids,
                text="\n\n".join(rendered_parts).rstrip(),
            )
        )
    return question_parts, questions


def analyze_page_layout(
    page_width: float,
    page_height: float,
    lines: list[Line],
    binary_image: np.ndarray | None = None,
) -> tuple[PageLayout, list[Rect | None], list[Question]]:
    height, width = binary_image.shape[:2]
    scale_x = width / page_width
    scale_y = height / page_height

    def to_pixel_rect(rect: Rect) -> PixelRect:
        return pdf_rect_to_pixel_rect(rect, scale_x, scale_y)

    def to_pdf_rect(rect: PixelRect) -> Rect:
        return pixel_rect_to_pdf_rect(rect, scale_x, scale_y)

    anchors = find_question_anchors(lines, page_width)

    # Use anchor x positions to infer the coarse column starts.
    column_starts = cluster_anchor_starts(anchors, page_width)
    columns = build_columns(column_starts, page_width, page_height)

    # Group anchors by their nearest coarse column.
    anchors_by_column: dict[int, list[Anchor]] = {column.index: [] for column in columns}
    for anchor in anchors:
        if not columns:
            continue
        column = min(columns, key=lambda item: abs(item.start_x - anchor.rect.x_min))
        anchors_by_column[column.index].append(anchor)

    # Tighten each column vertically to the first and last anchor it contains.
    updated_columns: list[Column] = []
    for column in columns:
        column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.rect.y_min)
        if column_anchors:
            top = column_anchors[0].rect.y_min
            bottom = column_anchors[-1].rect.y_max
        else:
            top = 0.0
            bottom = page_height
        updated_columns.append(
            Column(
                index=column.index,
                rect=Rect(
                    x_min=column.rect.x_min,
                    y_min=top,
                    x_max=column.rect.x_max,
                    y_max=bottom,
                ),
                start_x=column.start_x,
            )
        )

    # Tighten each column's right edge using the widest line that mostly belongs to it.
    final_columns: list[Column] = []
    for column in updated_columns:
        column_lines = lines_in_rect(lines, column.rect, min_overlap_ratio=0.8)
        if column_lines:
            right = min(column.rect.x_max, max(line.rect.x_max for line in column_lines))
        else:
            right = column.rect.x_max
        final_columns.append(
            Column(
                index=column.index,
                rect=Rect(
                    x_min=column.rect.x_min,
                    y_min=column.rect.y_min,
                    x_max=right,
                    y_max=column.rect.y_max,
                ),
                start_x=column.start_x,
            )
        )

    boundary_blank_rects: list[Rect | None] = [None] * (len(final_columns) + 1)
    if binary_image is not None and final_columns:
        if scale_x is None or scale_y is None:
            binary_height, binary_width = binary_image.shape[:2]
            scale_x = binary_width / page_width if page_width > 0 else 1.0
            scale_y = binary_height / page_height if page_height > 0 else 1.0
        assert scale_x is not None and scale_y is not None

        def search_blank_rect(search_rect: Rect) -> Rect | None:
            pixel_result = find_largest_blank_rect_in_rect(binary_image,
                                                           to_pixel_rect(search_rect))
            return to_pdf_rect(pixel_result) if pixel_result else None

        first_column = final_columns[0]
        boundary_blank_rects[0] = search_blank_rect(
            Rect(
                x_min=first_column.rect.x_min - 24.0,
                y_min=0.0,
                x_max=first_column.rect.x_min,
                y_max=page_height,
            )
        )

        for idx in range(len(final_columns) - 1):
            left_column = final_columns[idx]
            right_column = final_columns[idx + 1]
            y_min = 0
            y_max = page_height
            boundary_blank_rects[idx + 1] = search_blank_rect(
                Rect(
                    x_min=left_column.rect.x_max,
                    y_min=y_min,
                    x_max=right_column.rect.x_min,
                    y_max=y_max,
                )
            )

        last_column = final_columns[-1]
        boundary_blank_rects[-1] = search_blank_rect(
            Rect(
                x_min=last_column.rect.x_max,
                y_min=0.0,
                x_max=last_column.rect.x_max + 24.0,
                y_max=page_height,
            )
        )

        # print(boundary_blank_rects)
        refined_columns: list[Column] = []
        for idx, column in enumerate(final_columns):
            # find anchors of this column, order by y
            column_anchors = sorted(anchors_by_column.get(column.index, []), key=lambda item: item.rect.y_min)
            left_blank = boundary_blank_rects[idx]
            right_blank = boundary_blank_rects[idx + 1]

            assert left_blank and right_blank
            top = max(left_blank.y_min, right_blank.y_min)
            bottom = min(left_blank.y_max, right_blank.y_max)
            left = left_blank.x_max
            right = right_blank.x_min

            if column_anchors and column_anchors[0].question_no == "1":
                top = column_anchors[0].rect.y_min
            refined_columns.append(
                Column(
                    index=column.index,
                    rect=Rect(
                        x_min=left,
                        y_min=top,
                        x_max=right,
                        y_max=bottom,
                    ),
                    start_x=column.start_x,
                )
            )
        final_columns = refined_columns

        # If the bottom of a column is followed by a contiguous blank band,
        # trim the column bottom up to the start of that blank band.
        trimmed_columns: list[Column] = []
        for column in final_columns:
            pixel_rect = to_pixel_rect(column.rect)
            blank_intervals = find_blank_y_intervals_in_rect(binary_image, pixel_rect)
            new_bottom = column.rect.y_max
            new_top = column.rect.y_min
            if blank_intervals:
                bottom_blank = blank_intervals[-1]
                if bottom_blank.bottom >= pixel_rect.bottom:
                    # print(f"found bottom blank {bottom_blank} for {column}")
                    new_bottom = min(new_bottom, bottom_blank.top / scale_y)
                top_blank = blank_intervals[0]
                if top_blank.top <= pixel_rect.top:
                    new_top = max(new_top, top_blank.bottom / scale_y)
                    # print(f"found top blank {top_blank} for {column}")
            trimmed_columns.append(
                Column(
                    index=column.index,
                    rect=Rect(
                        x_min=column.rect.x_min,
                        y_min=new_top,
                        x_max=column.rect.x_max,
                        y_max=new_bottom,
                    ),
                    start_x=column.start_x,
                )
            )
        final_columns = trimmed_columns

    question_parts, questions = build_question_parts(final_columns, anchors_by_column, lines)

    page_layout = PageLayout(
        question_parts=question_parts,
        columns=final_columns,
        is_exam_page=bool(anchors),
        reasons=[],
    )

    return page_layout, boundary_blank_rects, questions


def create_soft_binary_image(raw_image: Image) -> np.ndarray:
    page_gray = np.asarray(raw_image.convert("L"))
    otsu_threshold, _ = cv2.threshold(
        page_gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    effective_threshold = int(min(otsu_threshold, SOFT_BINARY_MAX_THRESHOLD))
    processed = page_gray < effective_threshold

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        processed.astype(np.uint8),
        connectivity=8,
    )
    cleaned = np.zeros_like(processed, dtype=np.uint8)
    for label_id in range(1, num_labels):
        width_i = int(stats[label_id, cv2.CC_STAT_WIDTH])
        height_i = int(stats[label_id, cv2.CC_STAT_HEIGHT])
        area = width_i * height_i
        if area >= 2 or width_i >= 2 or height_i >= 2:
            cleaned[labels == label_id] = 1

    return ~cleaned.astype(bool)


def render_page_image(pdf_path: Path, page_no: int, dpi: int = 180) -> Image.Image:
    with tempfile.TemporaryDirectory(prefix="exam-paper-render-") as temp_dir:
        output_base = Path(temp_dir) / "page"
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
            ]
        )
        output_path = output_base.with_suffix(".png")
        with Image.open(output_path) as image:
            return image.copy()


def parse_exam_paper(
    pdf_file: str,
    recreate: bool = False,
    dpi: int = DEFAULT_DPI,
    page_no: int | None = None,
) -> ExamPaper:
    work_dir = create_output_dir(pdf_file)
    exam_paper = ExamPaper(work_dir=work_dir, dpi=dpi)

    if exam_paper.ready() and not recreate:
        return exam_paper

    if recreate and work_dir.exists():
        shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    total_pages = get_total_pages(Path(pdf_file))
    if not exam_paper.ready() or recreate:
        document_info = DocumentInfo(original_file_name=pdf_file, page_count=total_pages)
        exam_paper.save_document(document_info)

    exam_paper.debug_dir.mkdir(parents=True, exist_ok=True)
    page_nos = [page_no] if page_no is not None else list(range(1, total_pages + 1))
    for page_no in page_nos:
        if exam_paper.get_page_info(page_no):
            continue
        t0 = time.perf_counter()
        page_raw = exam_paper.get_page_raw_image(page_no)
        if page_raw is None:
            page_raw = render_page_image(exam_paper.document_path, page_no, dpi)
            exam_paper.save_page_raw_image(page_no, page_raw)

        page_binary = exam_paper.get_page_binary_image(page_no)
        if page_binary is None:
            page_binary = create_soft_binary_image(page_raw)
            exam_paper.save_page_binary_image(page_no, page_binary)

        t1 = time.perf_counter()
        page_width, page_height, lines = parse_bbox_page(exam_paper.document_path, page_no)
        # fix page width and height, make scale value can compute via dpi
        page_width = page_raw.width*72.0/dpi
        page_height = page_raw.height*72.0/dpi

        t1a = time.perf_counter()
        page_layout, blank_rects, questions = analyze_page_layout(
            page_width,
            page_height,
            lines,
            page_binary,
        )
        t2 = time.perf_counter()
        page_info = PageInfo(
            page_no=page_no,
            width=page_width,
            height=page_height,
            pixel_width=int(page_binary.shape[1]),
            pixel_height=int(page_binary.shape[0]),
            lines=lines,
            layout=page_layout,
            questions=questions,
        )
        exam_paper.save_page_info(page_info)

        page_image = page_raw
        try:
            t3 = time.perf_counter()
            marked = draw_rects_on_image(
                page_image,
                [column.rect for column in page_layout.columns]
                + [rect for rect in blank_rects if rect is not None],
                page_info.width,
                page_info.height,
            )
            t4 = time.perf_counter()
            marked.save(exam_paper.debug_dir / f"p{page_no}_columns.png")
            question_part_marked = draw_rects_on_image(
                page_image,
                [part.rect for part in page_layout.question_parts],
                page_info.width,
                page_info.height,
            )
            question_part_marked.save(exam_paper.debug_dir / f"p{page_no}_parts.png")
            t5 = time.perf_counter()
        finally:
            page_image.close()
        print(
            f"page {page_no} timings: "
            f"soft_binary={(t1 - t0):.3f}s, "
            f"bbox={(t1a - t1):.3f}s, "
            f"layout={(t2 - t1a):.3f}s, "
            f"load_raw={(t3 - t2):.3f}s, "
            f"draw={(t4 - t3):.3f}s, "
            f"save={(t5 - t4):.3f}s, "
            f"total={(t5 - t0):.3f}s"
        )
    return exam_paper


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="exam_paper_parser.py",
        description="Create an output directory for an exam paper PDF.",
    )
    parser.add_argument("pdf_file", help="PDF file name or path")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Rebuild the output directory even if parsed data already exists",
    )
    parser.add_argument(
        "--p",
        type=int,
        help="Only parse a single page number",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    exam_paper = parse_exam_paper(args.pdf_file, recreate=args.recreate, page_no=args.p)
    print(exam_paper.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
