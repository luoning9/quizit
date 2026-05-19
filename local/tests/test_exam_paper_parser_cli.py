import json
import os
import io
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from PIL import Image


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
LOCAL_DIR = REPO_ROOT / "local"
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from exam_paper_parser import (  # noqa: E402
    Column,
    ExamPaper,
    PageInfo,
    PageLayout,
    Question,
    QuestionPart,
    Rect,
    parse_args,
    parse_output_target,
    question_binary_png_path,
    question_png_path,
    question_output_payload,
    main,
    save_question_png,
    save_question_binary_png,
)


class ExamPaperParserCliTests(unittest.TestCase):
    def test_parse_args_supports_pdf_and_dir_modes(self) -> None:
        pdf_args = parse_args(["--pdf", "/tmp/input.pdf"])
        self.assertEqual(pdf_args.pdf_file, "/tmp/input.pdf")
        self.assertIsNone(pdf_args.work_dir)
        self.assertFalse(pdf_args.recreate)
        self.assertIsNone(pdf_args.page)
        self.assertIsNone(pdf_args.output)
        self.assertFalse(pdf_args.png)

        dir_args = parse_args(["--dir", "/tmp/work"])
        self.assertIsNone(dir_args.pdf_file)
        self.assertEqual(dir_args.work_dir, "/tmp/work")
        self.assertFalse(dir_args.recreate)
        self.assertIsNone(dir_args.page)
        self.assertIsNone(dir_args.output)
        self.assertFalse(dir_args.png)

    def test_parse_args_supports_page_and_output(self) -> None:
        args = parse_args(["--pdf", "/tmp/input.pdf", "--page", "2", "--output", "p2_q3", "--png"])
        self.assertEqual(args.page, 2)
        self.assertEqual(args.output, (2, 3))
        self.assertTrue(args.png)

    def test_parse_output_target_rejects_bad_format(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--pdf", "/tmp/input.pdf", "--output", "2-3"])

    def test_parse_args_rejects_dir_with_recreate(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--dir", "/tmp/work", "--recreate"])

    def test_parse_args_rejects_page_mismatch_for_output(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--pdf", "/tmp/input.pdf", "--page", "1", "--output", "p2_q3"])

    def test_parse_args_rejects_png_without_output(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--pdf", "/tmp/input.pdf", "--png"])

    def test_parse_output_target_parses_page_and_question(self) -> None:
        self.assertEqual(parse_output_target("p12_q34"), (12, 34))

    def test_question_png_path_adds_suffix_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            directory = Path(tmp)
            first = question_png_path(1, 2, directory)
            self.assertEqual(first.name, "question_q1_q2.png")
            first.write_bytes(b"first")
            second = question_png_path(1, 2, directory)
            self.assertEqual(second.name, "question_q1_q2.png")

    def test_question_binary_png_path_returns_binary_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            directory = Path(tmp)
            self.assertEqual(question_binary_png_path(1, 2, directory).name, "question_q1_q2_binary.png")

    def test_question_output_payload_serializes_question_and_parts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp)
            (work_dir / "p2").mkdir(parents=True, exist_ok=True)
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 2}),
                encoding="utf-8",
            )

            page_info = PageInfo(
                page_no=2,
                width=100.0,
                height=200.0,
                pixel_width=100,
                pixel_height=200,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="2. Example",
                            rect=Rect(1.0, 2.0, 3.0, 4.0),
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
                        part_ids=[],
                        text="",
                    ),
                    Question(
                        question_no=2,
                        part_ids=[],
                        text="",
                    ),
                    Question(
                        question_no=3,
                        part_ids=[0],
                        text="2. Example",
                    )
                ],
            )

            paper = ExamPaper(work_dir)
            paper.save_page_info(page_info)

            payload = question_output_payload(paper, 2, 3)
            self.assertEqual(payload["page_no"], 2)
            self.assertEqual(payload["question_no"], 3)
            self.assertEqual(payload["question"]["text"], "2. Example")
            self.assertEqual(payload["parts"][0]["rect"]["x_min"], 1.0)

    def test_save_question_png_writes_png_to_requested_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp) / "work"
            output_dir = Path(tmp) / "out"
            work_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (2, 2), "white").save(page_dir / "raw.png")
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=2,
                pixel_height=2,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Example",
                            rect=Rect(0.0, 0.0, 2.0, 2.0),
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
                        text="1. Example",
                    )
                ],
            )

            paper = ExamPaper(work_dir, dpi=72)
            paper.save_page_info(page_info)

            first = save_question_png(paper, 1, 1, output_dir=output_dir)
            self.assertEqual(first, (output_dir / "question_q1_q1.png", True))
            self.assertTrue(first[0].exists())

            second = save_question_png(paper, 1, 1, output_dir=output_dir)
            self.assertEqual(second, (output_dir / "question_q1_q1.png", False))
            self.assertTrue(second[0].exists())
            self.assertEqual(second[0].read_bytes(), first[0].read_bytes())

    def test_save_question_png_skips_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp) / "work"
            output_dir = Path(tmp) / "output"
            work_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (2, 2), "white").save(page_dir / "raw.png")
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=2,
                pixel_height=2,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Example",
                            rect=Rect(0.0, 0.0, 2.0, 2.0),
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
                        text="1. Example",
                    )
                ],
            )

            paper = ExamPaper(work_dir, dpi=72)
            paper.save_page_info(page_info)

            target = output_dir / "question_q1_q1.png"
            target.write_bytes(b"keep-me")

            path, created = save_question_png(paper, 1, 1, output_dir=output_dir)
            self.assertEqual(path, target)
            self.assertFalse(created)
            self.assertEqual(target.read_bytes(), b"keep-me")

    def test_save_question_binary_png_writes_binary_png_to_requested_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp) / "work"
            output_dir = Path(tmp) / "out"
            work_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            page_dir = work_dir / "p1"
            page_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (2, 2), "white").save(page_dir / "raw.png")
            Image.new("L", (2, 2), 255).save(page_dir / "soft_binary.png")
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=2,
                pixel_height=2,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Example",
                            rect=Rect(0.0, 0.0, 2.0, 2.0),
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
                        text="1. Example",
                    )
                ],
            )

            paper = ExamPaper(work_dir, dpi=72)
            paper.save_page_info(page_info)

            first = save_question_binary_png(paper, 1, 1, output_dir=output_dir)
            self.assertEqual(first, (output_dir / "question_q1_q1_binary.png", True))
            self.assertTrue(first[0].exists())

            second = save_question_binary_png(paper, 1, 1, output_dir=output_dir)
            self.assertEqual(second, (output_dir / "question_q1_q1_binary.png", False))
            self.assertEqual(second[0].read_bytes(), first[0].read_bytes())

    def test_main_reports_saved_png_path_when_requested(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            root = Path(tmp)
            work_dir = root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )
            (work_dir / "p1").mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (4, 4), "white").save(work_dir / "p1" / "raw.png")
            Image.new("L", (4, 4), 255).save(work_dir / "p1" / "soft_binary.png")

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=4,
                pixel_height=4,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Example",
                            rect=Rect(0.0, 0.0, 2.0, 2.0),
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
                        text="1. Example",
                    )
                ],
            )
            ExamPaper(work_dir).save_page_info(page_info)

            cwd = Path.cwd()
            try:
                os.chdir(root)
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    rc = main(["--dir", str(work_dir), "--output", "p1_q1", "--png"])
            finally:
                os.chdir(cwd)

            self.assertEqual(rc, 0)
            self.assertIn('"page_no": 1', stdout.getvalue())
            self.assertIn("saved question image:", stderr.getvalue())
            self.assertIn("saved question binary image:", stderr.getvalue())
            self.assertTrue((work_dir / "output" / "question_q1_q1.png").exists())
            self.assertTrue((work_dir / "output" / "question_q1_q1_binary.png").exists())

    def test_main_png_warns_when_binary_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            root = Path(tmp)
            work_dir = root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )
            (work_dir / "p1").mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (4, 4), "white").save(work_dir / "p1" / "raw.png")

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=4,
                pixel_height=4,
                lines=[],
                layout=PageLayout(
                    question_parts=[
                        QuestionPart(
                            anchor_text="1. Example",
                            rect=Rect(0.0, 0.0, 2.0, 2.0),
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
                        text="1. Example",
                    )
                ],
            )
            ExamPaper(work_dir).save_page_info(page_info)

            cwd = Path.cwd()
            try:
                os.chdir(root)
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    rc = main(["--dir", str(work_dir), "--output", "p1_q1", "--png"])
            finally:
                os.chdir(cwd)

            self.assertEqual(rc, 0)
            self.assertIn("saved question image:", stderr.getvalue())
            self.assertIn("question binary image skipped:", stderr.getvalue())
            self.assertTrue((work_dir / "output" / "question_q1_q1.png").exists())
            self.assertFalse((work_dir / "output" / "question_q1_q1_binary.png").exists())

    def test_question_output_payload_reports_missing_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp)
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )

            paper = ExamPaper(work_dir)

            with self.assertRaisesRegex(ValueError, r"page 2 not found"):
                question_output_payload(paper, 2, 1)

    def test_question_output_payload_reports_missing_question(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_paper_cli_") as tmp:
            work_dir = Path(tmp)
            (work_dir / "p1").mkdir(parents=True, exist_ok=True)
            (work_dir / "document_info.json").write_text(
                json.dumps({"original_file_name": "paper.pdf", "page_count": 1}),
                encoding="utf-8",
            )

            page_info = PageInfo(
                page_no=1,
                width=100.0,
                height=200.0,
                pixel_width=100,
                pixel_height=200,
                lines=[],
                layout=PageLayout(
                    question_parts=[],
                    columns=[],
                    is_exam_page=True,
                    reasons=[],
                ),
                questions=[
                    Question(
                        question_no=1,
                        part_ids=[],
                        text="",
                    )
                ],
            )

            paper = ExamPaper(work_dir)
            paper.save_page_info(page_info)

            with self.assertRaisesRegex(ValueError, r"question 2 not found on page 1"):
                question_output_payload(paper, 1, 2)


if __name__ == "__main__":
    unittest.main()
