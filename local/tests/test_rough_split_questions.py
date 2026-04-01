import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
SCRIPT_PATH = REPO_ROOT / "local" / "rough_split_questions.py"
SAMPLE_PDF = Path("/Users/jason/Downloads/53quiz_sample.pdf")


class RoughSplitQuestionsSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_PDF.exists():
            raise unittest.SkipTest(f"sample pdf not found: {SAMPLE_PDF}")

        cls.tmpdir = Path(tempfile.mkdtemp(prefix="quizit_split_tests_"))
        cls.out_dir = cls.tmpdir / "out"

        subprocess.run(
            [
                "python3",
                str(SCRIPT_PATH),
                str(SAMPLE_PDF),
                "--out",
                str(cls.out_dir),
                "--text-source",
                "hybrid",
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        with (cls.out_dir / "manifest.json").open("r", encoding="utf-8") as f:
            cls.manifest = json.load(f)

        cls.by_question = {str(item["question_no"]): item for item in cls.manifest}

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmpdir") and cls.tmpdir.exists():
            shutil.rmtree(cls.tmpdir)

    def get_question(self, question_no: str) -> dict:
        self.assertIn(question_no, self.by_question, f"missing question {question_no}")
        return self.by_question[question_no]

    def assert_types(self, question_no: str, expected: list[str]) -> None:
        record = self.get_question(question_no)
        actual = [img["type"] for img in record["images"]]
        self.assertEqual(actual, expected, f"unexpected image types for q{question_no}")

    def assert_columns(self, question_no: str, expected: list[int]) -> None:
        record = self.get_question(question_no)
        actual = [img["column"] for img in record["images"]]
        self.assertEqual(actual, expected, f"unexpected columns for q{question_no}")

    def test_q05_body_visual_body(self) -> None:
        self.assert_types("5", ["body", "visual", "body"])
        self.assert_columns("5", [1, 1, 1])

    def test_q07_single_body(self) -> None:
        self.assert_types("7", ["body"])
        self.assert_columns("7", [2])

    def test_q08_single_body(self) -> None:
        self.assert_types("8", ["body"])
        self.assert_columns("8", [2])

    def test_q09_body_visual_body(self) -> None:
        self.assert_types("9", ["body", "visual", "body"])
        self.assert_columns("9", [2, 2, 2])

    def test_q10_cross_column_continuation(self) -> None:
        self.assert_types("10", ["body", "body"])
        self.assert_columns("10", [2, 3])

    def test_q16_contains_table_segment(self) -> None:
        self.assert_types("16", ["body", "visual", "body", "table", "body"])
        self.assert_columns("16", [1, 1, 1, 2, 2])

    def test_q17_body_table_visual_body(self) -> None:
        self.assert_types("17", ["body", "table", "visual", "body"])
        self.assert_columns("17", [2, 2, 2, 2])


if __name__ == "__main__":
    unittest.main()
