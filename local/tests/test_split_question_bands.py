import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path("/Users/jason/Documents/GitHub/quizit")
SCRIPT_PATH = REPO_ROOT / "local" / "split_question_bands.py"
FIXTURE_DIR = REPO_ROOT / "local" / "tests" / "fixtures" / "split_question_bands"


class SplitQuestionBandsFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not FIXTURE_DIR.exists():
            raise unittest.SkipTest(f"fixture dir not found: {FIXTURE_DIR}")

        cls.tmpdir = Path(tempfile.mkdtemp(prefix="quizit_split_question_bands_tests_"))
        cls.out_dir = cls.tmpdir / "out"
        cls.out_dir.mkdir(parents=True, exist_ok=True)

        cls.expected = {
            "q05_single_page": ["body", "visual", "body"],
            "q07_single_page": ["body"],
            "q08_single_page": ["body"],
            "q09_single_page": ["body", "visual", "body"],
            "q10_single_page_cross_column": ["body"],
            "q16_single_page": ["body", "visual", "body", "table", "body"],
            "q17_single_page": ["body", "table", "visual", "body"],
        }

        cls.results = {}
        for stem in cls.expected:
            fixture_pdf = FIXTURE_DIR / f"{stem}.pdf"
            if not fixture_pdf.exists():
                raise unittest.SkipTest(f"fixture pdf not found: {fixture_pdf}")

            target_out = cls.out_dir / stem
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    str(fixture_pdf),
                    "--out",
                    str(target_out),
                ],
                cwd=REPO_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            result_path = target_out / f"{stem}_merged_bands.json"
            with result_path.open("r", encoding="utf-8") as f:
                cls.results[stem] = json.load(f)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmpdir") and cls.tmpdir.exists():
            shutil.rmtree(cls.tmpdir)

    def assert_types(self, stem: str, expected: list[str]) -> None:
        actual = [band["kind"] for band in self.results[stem]["merged_bands"]]
        self.assertEqual(actual, expected, f"unexpected merged band kinds for {stem}")

    def test_q05_body_visual_body(self) -> None:
        self.assert_types("q05_single_page", self.expected["q05_single_page"])

    def test_q07_single_body(self) -> None:
        self.assert_types("q07_single_page", self.expected["q07_single_page"])

    def test_q08_single_body(self) -> None:
        self.assert_types("q08_single_page", self.expected["q08_single_page"])

    def test_q09_body_visual_body(self) -> None:
        self.assert_types("q09_single_page", self.expected["q09_single_page"])

    def test_q10_cross_column_continuation(self) -> None:
        self.assert_types("q10_single_page_cross_column", self.expected["q10_single_page_cross_column"])

    def test_q16_contains_table_segment(self) -> None:
        self.assert_types("q16_single_page", self.expected["q16_single_page"])

    def test_q17_body_table_visual_body(self) -> None:
        self.assert_types("q17_single_page", self.expected["q17_single_page"])


if __name__ == "__main__":
    unittest.main()
