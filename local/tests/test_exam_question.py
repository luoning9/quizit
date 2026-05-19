import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
LOCAL_DIR = REPO_ROOT / "local"
EXAM_QUESTION_FIXTURE_DIR = REPO_ROOT / "local" / "tests" / "fixtures" / "exam_question"
Q05_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "q05_binary.png"
Q07_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "q07_binary.png"
Q08_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "q08_binary.png"
Q09_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "q09_binary.png"
Q10_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "q10_binary.png"
P2_Q3_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "p2_q3_binary.png"
P2_Q4_BINARY_FIXTURE = EXAM_QUESTION_FIXTURE_DIR / "p2_q4_binary.png"
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from exam_question import (  # noqa: E402
    Band,
    BinaryImageContext,
    PixelRow,
    PixelRect,
    SplitResult,
    TextBox,
    _text_boxes_to_rows,
    draw_rects_in_image,
    split_question_bands,
)


class BinaryImageContextTests(unittest.TestCase):
    def test_find_text_boxes_respects_coverage_threshold(self) -> None:
        box = TextBox(
            text="TXT_1",
            rect=PixelRect(left=2, top=2, right=6, bottom=6),
        )
        context = BinaryImageContext(np.zeros((10, 10), dtype=np.uint8), [box])

        self.assertEqual(
            context.find_text_boxes(PixelRect(left=2, top=2, right=6, bottom=5), coverage=0.75),
            [box],
        )
        self.assertEqual(
            context.find_text_boxes(PixelRect(left=2, top=2, right=6, bottom=5), coverage=0.76),
            [],
        )
        self.assertEqual(context.find_text_boxes_in_row(PixelRow(top=2, bottom=5), coverage=0.75), [box])


class TextRowsTests(unittest.TestCase):
    def test_text_boxes_to_rows_drops_overlapping_rows(self) -> None:
        boxes = [
            TextBox("A", rect=PixelRect(left=10, top=10, right=20, bottom=20)),
            TextBox("B", rect=PixelRect(left=12, top=18, right=22, bottom=28)),
        ]

        rows = _text_boxes_to_rows(boxes, padding=2)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], PixelRow(top=8, bottom=22))


class DrawRectsInImageTests(unittest.TestCase):
    def test_draw_rects_in_image_returns_marked_copy(self) -> None:
        image = Image.new("RGB", (20, 20), "white")
        marked = draw_rects_in_image(
            image,
            [(PixelRect(left=2, top=3, right=10, bottom=12), "A", "B")],
        )

        self.assertEqual(marked.size, image.size)
        self.assertIsNot(marked, image)


class SplitQuestionBandsTests(unittest.TestCase):
    def assert_fixture_merged_kinds(self, fixture_path: Path, expected: list[str]) -> None:
        if not fixture_path.exists():
            raise unittest.SkipTest(f"fixture image not found: {fixture_path}")

        with Image.open(fixture_path) as image:
            result = split_question_bands(image.copy())

        self.assertEqual([band.type for band in result.merged_bands], expected)

    def test_split_question_bands_returns_single_visual_gap_when_no_text(self) -> None:
        image = Image.new("L", (12, 10), 255)

        result = split_question_bands(image)

        self.assertIsInstance(result, SplitResult)
        self.assertIs(result.image, image)
        self.assertEqual(result.text_blocks, [])
        self.assertEqual(result.text_rows, [])
        self.assertEqual(len(result.split_bands), 1)
        self.assertEqual(result.split_bands, result.typed_bands)
        self.assertEqual(result.split_bands, result.merged_bands)
        self.assertEqual(result.split_bands[0].type, "visual_gap")
        self.assertTrue(result.split_bands[0].is_gap)

    def test_split_question_bands_threads_pipeline_outputs(self) -> None:
        image = Image.new("L", (24, 24), 255)
        text_box = TextBox("TXT_1", rect=PixelRect(left=4, top=5, right=10, bottom=9))
        text_row = PixelRow(top=4, bottom=10)
        raw_band = Band(row=text_row, type="", is_gap=False)
        typed_band = Band(row=text_row, type="body", is_gap=False)
        merged_band = Band(row=text_row, type="body", is_gap=False)

        with (
            patch("exam_question._detect_text_boxes", return_value=[text_box]) as detect_mock,
            patch("exam_question._text_boxes_to_rows", return_value=[text_row]) as rows_mock,
            patch("exam_question._split_to_raw_bands", return_value=[raw_band]) as split_mock,
            patch("exam_question._estimate_text_height", return_value=4) as height_mock,
            patch("exam_question._classify_bands_in_order", return_value=([typed_band], [4])) as classify_mock,
            patch("exam_question._assign_band_connectivity", return_value=[typed_band]) as connect_mock,
            patch("exam_question._merge_typed_bands", return_value=([merged_band], [{"stage": "final"}])) as merge_mock,
        ):
            result = split_question_bands(image)

        self.assertEqual(result.text_blocks, [text_box])
        self.assertEqual(result.text_rows, [text_row])
        self.assertEqual(result.split_bands, [raw_band])
        self.assertEqual(result.typed_bands, [typed_band])
        self.assertEqual(result.merged_bands, [merged_band])
        detect_mock.assert_called_once_with(image)
        rows_mock.assert_called_once_with([text_box])
        split_mock.assert_called_once()
        height_mock.assert_called_once()
        classify_mock.assert_called_once()
        connect_mock.assert_called_once()
        merge_mock.assert_called_once()

    def test_split_question_bands_q05_binary_fixture(self) -> None:
        if not Q05_BINARY_FIXTURE.exists():
            raise unittest.SkipTest(f"fixture image not found: {Q05_BINARY_FIXTURE}")

        with Image.open(Q05_BINARY_FIXTURE) as image:
            result = split_question_bands(image.copy())

        self.assertEqual([band.type for band in result.merged_bands], ["body", "visual_gap", "body"])
        self.assertEqual(
            [(band.row.top, band.row.bottom, band.is_gap) for band in result.merged_bands],
            [(0, 187, False), (187, 326, False), (326, 490, False)],
        )

    def test_split_question_bands_q07_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(Q07_BINARY_FIXTURE, ["body"])

    def test_split_question_bands_q08_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(Q08_BINARY_FIXTURE, ["body"])

    def test_split_question_bands_q09_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(Q09_BINARY_FIXTURE, ["body", "visual_gap", "body"])

    def test_split_question_bands_q10_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(Q10_BINARY_FIXTURE, ["body", "visual_gap", "body"])

    def test_split_question_bands_p2_q3_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(P2_Q3_BINARY_FIXTURE, ["body", "table", "visual_gap", "body"])

    def test_split_question_bands_p2_q4_binary_fixture(self) -> None:
        self.assert_fixture_merged_kinds(P2_Q4_BINARY_FIXTURE, ["body"])


if __name__ == "__main__":
    unittest.main()
