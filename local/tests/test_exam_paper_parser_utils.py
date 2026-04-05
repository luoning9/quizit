import sys
import unittest
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
LOCAL_DIR = REPO_ROOT / "local"
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from exam_paper_parser import (  # noqa: E402
    Anchor,
    ExamPaper,
    Column,
    Line,
    PixelRect,
    Rect,
    PageInfo,
    PageLayout,
    Question,
    QuestionPart,
    build_question_parts,
    largest_true_rectangle,
    find_blank_y_intervals_in_rect,
    find_largest_blank_rect_in_rect,
    lines_in_rect,
    text_in_rect,
    pdf_rect_to_pixel_rect,
    pixel_rect_to_pdf_rect,
    rect_area,
    rect_intersection_area,
)


class ExamPaperParserUtilsTests(unittest.TestCase):
    def test_rect_area_handles_zero_and_negative_sizes(self) -> None:
        self.assertEqual(rect_area(Rect(1.0, 1.0, 1.0, 5.0)), 0.0)
        self.assertEqual(rect_area(Rect(1.0, 5.0, 4.0, 5.0)), 0.0)
        self.assertEqual(rect_area(Rect(4.0, 4.0, 2.0, 6.0)), 0.0)
        self.assertEqual(rect_area(Rect(1.0, 2.0, 4.0, 6.0)), 12.0)

    def test_rect_intersection_area_handles_touching_edges(self) -> None:
        self.assertEqual(
            rect_intersection_area(Rect(0.0, 0.0, 2.0, 2.0), Rect(2.0, 0.0, 4.0, 2.0)),
            0.0,
        )
        self.assertEqual(
            rect_intersection_area(Rect(0.0, 0.0, 3.0, 3.0), Rect(1.0, 1.0, 4.0, 4.0)),
            4.0,
        )
        self.assertEqual(
            rect_intersection_area(Rect(0.0, 0.0, 5.0, 5.0), Rect(1.0, 1.0, 2.0, 2.0)),
            1.0,
        )

    def test_rect_pixel_round_trip_uses_floor_and_ceil(self) -> None:
        rect = Rect(1.2, 3.4, 5.1, 7.9)
        pixel_rect = pdf_rect_to_pixel_rect(rect, 2.0, 3.0)
        self.assertEqual(pixel_rect, PixelRect(2, 10, 11, 24))
        self.assertEqual(pixel_rect_to_pdf_rect(pixel_rect, 2.0, 3.0), Rect(1.0, 10 / 3.0, 5.5, 8.0))

    def test_largest_true_rectangle_handles_empty_and_single_cell_masks(self) -> None:
        self.assertIsNone(largest_true_rectangle(np.zeros((0, 0), dtype=bool)))
        self.assertEqual(
            largest_true_rectangle(np.array([[True]], dtype=bool)),
            PixelRect(0, 0, 1, 1),
        )

    def test_largest_true_rectangle_prefers_largest_area_not_widest_or_tallest(self) -> None:
        mask = np.array(
            [
                [1, 1, 0, 1],
                [1, 1, 0, 1],
                [0, 0, 0, 1],
            ],
            dtype=bool,
        )

        self.assertEqual(largest_true_rectangle(mask), PixelRect(0, 0, 2, 2))

    def test_largest_true_rectangle_respects_min_size_filters(self) -> None:
        mask = np.array(
            [
                [1, 1, 1],
                [1, 1, 1],
            ],
            dtype=bool,
        )

        self.assertIsNone(largest_true_rectangle(mask, min_width=4))
        self.assertIsNone(largest_true_rectangle(mask, min_height=3))
        self.assertEqual(largest_true_rectangle(mask, min_width=2, min_height=2), PixelRect(0, 0, 3, 2))

    def test_lines_in_rect_requires_full_overlap_by_default(self) -> None:
        lines = [
            Line("inside", Rect(1.0, 1.0, 3.0, 3.0)),
            Line("partial", Rect(0.0, 0.0, 2.0, 2.0)),
            Line("zero", Rect(5.0, 5.0, 5.0, 8.0)),
        ]
        rect = Rect(0.5, 0.5, 3.5, 3.5)

        matched = lines_in_rect(lines, rect)

        self.assertEqual([line.text for line in matched], ["inside"])

    def test_lines_in_rect_supports_threshold_boundaries(self) -> None:
        lines = [
            Line("half", Rect(0.0, 0.0, 4.0, 2.0)),
            Line("less", Rect(0.0, 0.0, 4.0, 2.0)),
        ]
        rect_half = Rect(2.0, 0.0, 6.0, 2.0)
        rect_less = Rect(2.1, 0.0, 6.0, 2.0)

        self.assertEqual([line.text for line in lines_in_rect([lines[0]], rect_half, 0.5)], ["half"])
        self.assertEqual(lines_in_rect([lines[1]], rect_less, 0.5), [])
        self.assertEqual([line.text for line in lines_in_rect(lines, rect_half, 0.0)], ["half", "less"])

    def test_text_in_rect_preserves_column_spacing(self) -> None:
        lines = [
            Line("A", Rect(0.0, 0.0, 1.0, 1.0)),
            Line("B", Rect(4.0, 0.0, 5.0, 1.0)),
        ]
        rect = Rect(0.0, 0.0, 10.0, 2.0)

        self.assertEqual(text_in_rect(lines, rect), "A   B")

    def test_text_in_rect_uses_fixed_overlap_threshold(self) -> None:
        lines = [
            Line("inside", Rect(0.0, 1.0, 6.0, 3.0)),
            Line("partial", Rect(0.0, 0.0, 2.0, 2.0)),
        ]
        rect = Rect(0.5, 0.5, 7.5, 3.5)

        self.assertEqual(text_in_rect(lines, rect), "inside")
        self.assertEqual(text_in_rect([], rect), "")

    def test_text_in_rect_inserts_blank_lines_for_vertical_gaps(self) -> None:
        lines = [
            Line("A", Rect(0.0, 0.0, 1.0, 1.0)),
            Line("B", Rect(0.0, 4.0, 1.0, 5.0)),
        ]
        rect = Rect(0.0, 0.0, 10.0, 6.0)

        self.assertEqual(text_in_rect(lines, rect), "A\n\n\nB")

    def test_find_blank_y_intervals_in_rect_handles_empty_and_edge_blank_rows(self) -> None:
        binary = np.array(
            [
                [1, 1, 1, 1],
                [0, 1, 1, 0],
                [1, 1, 1, 1],
                [1, 1, 1, 1],
                [0, 0, 1, 1],
                [1, 1, 1, 1],
            ],
            dtype=bool,
        )

        self.assertEqual(find_blank_y_intervals_in_rect(binary, PixelRect(0, 0, 0, 0)), [])
        self.assertEqual(find_blank_y_intervals_in_rect(binary, PixelRect(10, 10, 12, 12)), [])

        intervals = find_blank_y_intervals_in_rect(binary, PixelRect(0, 0, 4, 6))
        self.assertEqual(
            intervals,
            [
                PixelRect(0, 0, 4, 1),
                PixelRect(0, 2, 4, 4),
                PixelRect(0, 5, 4, 6),
            ],
        )

    def test_find_largest_blank_rect_in_rect_handles_empty_and_boundary_cases(self) -> None:
        binary = np.array(
            [
                [1, 1, 1],
                [1, 0, 1],
                [1, 1, 1],
            ],
            dtype=bool,
        )

        self.assertIsNone(find_largest_blank_rect_in_rect(np.zeros((0, 0), dtype=bool), PixelRect(0, 0, 1, 1)))
        self.assertIsNone(find_largest_blank_rect_in_rect(binary, PixelRect(5, 5, 6, 6)))
        self.assertEqual(
            find_largest_blank_rect_in_rect(binary, PixelRect(0, 0, 3, 3)),
            PixelRect(0, 0, 3, 1),
        )

    def test_find_largest_blank_rect_in_rect_clamps_search_window(self) -> None:
        binary = np.array(
            [
                [1, 1, 1, 1],
                [1, 0, 0, 1],
                [1, 0, 0, 1],
                [1, 1, 1, 1],
            ],
            dtype=bool,
        )

        self.assertEqual(
            find_largest_blank_rect_in_rect(binary, PixelRect(-5, -5, 10, 10)),
            PixelRect(0, 0, 4, 1),
        )
        self.assertIsNone(find_largest_blank_rect_in_rect(binary, PixelRect(0, 0, 4, 4), min_width=5))

    def test_get_page_raw_image_returns_full_image_and_cropped_region(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_utils_") as tmp:
            work_dir = Path(tmp)
            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)

            image = Image.new("RGB", (4, 4))
            pixels = []
            for y in range(4):
                for x in range(4):
                    pixels.append((x * 40, y * 40, (x + y) * 20))
            image.putdata(pixels)
            image.save(page_dir / "raw.png")

            exam_paper = ExamPaper(work_dir, dpi=72)

            full = exam_paper.get_page_raw_image(1)
            self.assertIsNotNone(full)
            self.assertEqual(full.size, (4, 4))
            self.assertEqual(full.getpixel((2, 3)), (80, 120, 100))

            cropped = exam_paper.get_page_raw_image(1, Rect(1.0, 1.0, 3.0, 3.0))
            self.assertIsNotNone(cropped)
            self.assertEqual(cropped.size, (2, 2))
            self.assertEqual(cropped.getpixel((0, 0)), full.getpixel((1, 1)))
            self.assertEqual(cropped.getpixel((1, 1)), full.getpixel((2, 2)))

            clamped = exam_paper.get_page_raw_image(1, Rect(-2.0, -2.0, 2.0, 2.0))
            self.assertIsNotNone(clamped)
            self.assertEqual(clamped.size, (2, 2))
            self.assertEqual(clamped.getpixel((0, 0)), full.getpixel((0, 0)))

    def test_get_page_binary_image_returns_full_image_and_cropped_region(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_utils_") as tmp:
            work_dir = Path(tmp)
            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)

            binary = np.array(
                [
                    [0, 1, 0, 1],
                    [1, 1, 0, 0],
                    [0, 0, 1, 1],
                    [1, 0, 1, 0],
                ],
                dtype=bool,
            )
            Image.fromarray((binary * 255).astype("uint8"), mode="L").save(page_dir / "soft_binary.png")

            exam_paper = ExamPaper(work_dir, dpi=72)

            full = exam_paper.get_page_binary_image(1)
            self.assertIsNotNone(full)
            self.assertEqual(full.shape, (4, 4))
            self.assertTrue(bool(full[0, 1]))
            self.assertFalse(bool(full[0, 0]))

            cropped = exam_paper.get_page_binary_image(1, Rect(1.0, 1.0, 3.0, 3.0))
            self.assertIsNotNone(cropped)
            self.assertEqual(cropped.shape, (2, 2))
            self.assertEqual(cropped.tolist(), [[True, False], [False, True]])

            clamped = exam_paper.get_page_binary_image(1, Rect(-2.0, -2.0, 2.0, 2.0))
            self.assertIsNotNone(clamped)
            self.assertEqual(clamped.shape, (2, 2))
            self.assertEqual(clamped.tolist(), [[False, True], [True, True]])

    def test_create_question_image_applies_padding_and_clamps_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_utils_") as tmp:
            work_dir = Path(tmp)
            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)

            image = Image.new("RGB", (4, 4), "black")
            pixels = []
            for y in range(4):
                for x in range(4):
                    pixels.append((x * 40, y * 40, (x + y) * 20))
            image.putdata(pixels)
            image.save(page_dir / "raw.png")

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=100.0,
                pixel_width=4,
                pixel_height=4,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Foo",
                            rect=Rect(1.0, 1.0, 3.0, 3.0),
                            column=0,
                            index_in_page=0,
                        )
                    ],
                    columns=[
                        Column(
                            index=0,
                            rect=Rect(0.0, 0.0, 100.0, 100.0),
                            start_x=0.0,
                        )
                    ],
                    is_exam_page=True,
                    reasons=[],
                ),
                questions=[
                    Question(
                        question_no=1,
                        part_ids=[0],
                        text="1. Foo",
                    )
                ],
            )

            writer = ExamPaper(work_dir)
            writer.save_page_info(page_info)

            reader = ExamPaper(work_dir)
            padded = reader.create_question_image(1, 1, padding=3)
            self.assertEqual(padded.size, (18, 18))
            self.assertEqual(padded.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(padded.getpixel((8, 8)), image.getpixel((2, 2)))
            self.assertEqual(padded.getpixel((9, 9)), image.getpixel((3, 3)))

            clamped = reader.create_question_image(1, 1, padding=99)
            self.assertEqual(clamped.size, (102, 102))
            self.assertEqual(clamped.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(clamped.getpixel((50, 50)), image.getpixel((2, 2)))

    def test_create_question_binary_image_preserves_blank_rows_and_padding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_utils_") as tmp:
            work_dir = Path(tmp)
            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)

            binary = np.array(
                [
                    [1, 1, 1, 1, 1, 1],
                    [1, 0, 0, 1, 0, 0],
                    [1, 0, 0, 1, 0, 0],
                    [1, 1, 1, 1, 1, 1],
                ],
                dtype=bool,
            )
            Image.fromarray((binary * 255).astype("uint8"), mode="L").save(page_dir / "soft_binary.png")

            page_info = PageInfo(
                page_no=1,
                width=6.0,
                height=4.0,
                pixel_width=6,
                pixel_height=4,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Foo",
                            rect=Rect(0.0, 1.0, 3.0, 3.0),
                            column=0,
                            index_in_page=0,
                        ),
                        QuestionPart(
                            anchor_text="",
                            rect=Rect(3.0, 1.0, 6.0, 3.0),
                            column=0,
                            index_in_page=1,
                        ),
                    ],
                    columns=[
                        Column(
                            index=0,
                            rect=Rect(0.0, 0.0, 6.0, 4.0),
                            start_x=0.0,
                        )
                    ],
                    is_exam_page=True,
                    reasons=[],
                ),
                questions=[
                    Question(
                        question_no=1,
                        part_ids=[0, 1],
                        text="",
                    )
                ],
            )

            writer = ExamPaper(work_dir, dpi=72)
            writer.save_page_info(page_info)

            reader = ExamPaper(work_dir, dpi=72)
            stitched = reader.create_question_binary_image(1, 1, gap_pt=1, padding=2)

            self.assertEqual(stitched.mode, "L")
            stitched_array = np.asarray(stitched) > 0
            self.assertEqual(stitched_array.shape, (9, 7))
            self.assertTrue(np.all(stitched_array[:2, :]))
            self.assertTrue(np.array_equal(stitched_array[2:4, 2:5], binary[1:3, 0:3]))
            self.assertTrue(np.all(stitched_array[4, :]))
            self.assertTrue(np.array_equal(stitched_array[5:7, 2:5], binary[1:3, 3:6]))
            self.assertTrue(np.all(stitched_array[7:, :]))

    def test_build_question_parts_populates_question_text(self) -> None:
        columns = [
            Column(
                index=0,
                rect=Rect(0.0, 10.0, 40.0, 80.0),
                start_x=0.0,
            )
        ]
        anchors_by_column = {
            0: [
                Anchor(
                    question_no="1",
                    text="1. Foo",
                    rect=Rect(0.0, 10.0, 10.0, 20.0),
                )
            ]
        }
        lines = [
            Line("1. Foo", Rect(0.0, 10.0, 10.0, 20.0)),
            Line("bar", Rect(0.0, 26.0, 6.0, 36.0)),
        ]

        question_parts, questions = build_question_parts(columns, anchors_by_column, lines)

        self.assertEqual(len(question_parts), 1)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].part_ids, [0])
        self.assertEqual(questions[0].question_no, 1)
        self.assertEqual(questions[0].text, "1. Foo\nbar")

    def test_get_question_reads_saved_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_utils_") as tmp:
            work_dir = Path(tmp)
            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=100,
                pixel_height=200,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Foo",
                            rect=Rect(0.0, 0.0, 10.0, 10.0),
                            column=0,
                            index_in_page=0,
                        )
                    ],
                    columns=[
                        Column(
                            index=0,
                            rect=Rect(0.0, 0.0, 10.0, 20.0),
                            start_x=0.0,
                        )
                    ],
                    is_exam_page=True,
                    reasons=[],
                ),
                questions=[
                    Question(
                        question_no=1,
                        part_ids=[0],
                        text="1. Foo",
                    )
                ],
            )

            writer = ExamPaper(work_dir)
            writer.save_page_info(page_info)

            reader = ExamPaper(work_dir)
            question = reader.get_question(1, 1)

            self.assertEqual(question.question_no, 1)
            self.assertEqual(question.part_ids, [0])
            self.assertEqual(question.text, "1. Foo")


if __name__ == "__main__":
    unittest.main()
