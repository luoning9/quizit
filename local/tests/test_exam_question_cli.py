import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr

from PIL import Image


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
LOCAL_DIR = REPO_ROOT / "local"
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from exam_question import Band  # noqa: E402
from exam_question import PixelRow  # noqa: E402
from exam_question import SplitResult  # noqa: E402
from exam_question import parse_args  # noqa: E402
from exam_question import main  # noqa: E402


class ExamQuestionCliTests(unittest.TestCase):
    def test_parser_exposes_binary_image_flag(self) -> None:
        args = parse_args(["--dir", "/tmp/work", "--page", "1", "--question", "2", "-b"])
        self.assertTrue(args.generate_binary_image)
        self.assertFalse(args.generate_image)

    def test_parser_allows_both_image_flags(self) -> None:
        args = parse_args(["--dir", "/tmp/work", "--page", "1", "--question", "2", "-g", "-b"])
        self.assertTrue(args.generate_image)
        self.assertTrue(args.generate_binary_image)

    def test_parser_supports_image_mode_without_dir_page_question(self) -> None:
        args = parse_args(["-i", "/tmp/question.png", "-g"])
        self.assertEqual(args.image_path, Path("/tmp/question.png"))
        self.assertIsNone(args.work_dir)
        self.assertIsNone(args.page_no)
        self.assertIsNone(args.question_no)
        self.assertTrue(args.generate_image)

    def test_parser_rejects_image_mode_with_dir_page_question(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["-i", "/tmp/question.png", "--dir", "/tmp/work", "--page", "1", "--question", "2"])

    def test_main_routes_image_mode_to_split_question_bands(self) -> None:
        with mock.patch("exam_question.split_question_bands") as split_mock, tempfile.TemporaryDirectory(prefix="quizit_exam_question_cli_") as tmp:
            image_path = Path(tmp) / "question.png"
            Image.new("L", (4, 4), 255).save(image_path)

            split_mock.return_value = SplitResult(
                image=Image.new("L", (4, 4), 255),
                text_blocks=[],
                split_bands=[Band(PixelRow(0, 4), "visual_gap", True)],
                typed_bands=[Band(PixelRow(0, 4), "visual_gap", True)],
                merged_bands=[Band(PixelRow(0, 4), "visual_gap", True)],
                text_rows=[],
            )

            main(["-i", str(image_path)])

            split_mock.assert_called_once()
            called_image = split_mock.call_args.args[0]
            self.assertEqual(called_image.mode, "L")

    def test_main_rejects_non_binary_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quizit_exam_question_cli_") as tmp:
            image_path = Path(tmp) / "question.png"
            Image.new("L", (4, 4), 128).save(image_path)

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
                main(["-i", str(image_path)])

            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("input image is not binary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
