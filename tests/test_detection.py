from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from document_extractor.detection import normalize_selector_input
from tests.mock_site import MockDocumentHandler


class SelectorInputTests(unittest.TestCase):
    def test_css_selector_is_unchanged(self):
        self.assertEqual(normalize_selector_input("img.ts-main-image"), "img.ts-main-image")

    def test_html_snippet_is_converted_to_css(self):
        self.assertEqual(
            normalize_selector_input('<img class="ts-main-image lazy" ...>'),
            "img.ts-main-image.lazy",
        )


@unittest.skipUnless(os.environ.get("RUN_EXTRACTOR_E2E") == "1", "test navigateur facultatif")
class EndToEndDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockDocumentHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_fully_automatic_extraction(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((Path(temp) / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["expected"], 5)
            self.assertEqual(manifest["detected"], 5)
            self.assertIn("full", manifest["reading_mode"]["action"])
            self.assertEqual(manifest["selector"], "img.ts-main-image")
            self.assertEqual(manifest["saved"], 5)
            self.assertEqual(manifest["missing"], [])
            archive_path = Path(temp) / "document.cbz"
            self.assertTrue(archive_path.is_file())
            self.assertFalse((Path(temp) / "images").exists())
            self.assertFalse((Path(temp) / ".komaforge-work").exists())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [f"page-{index:04d}.png" for index in range(1, 6)],
                )
            self.assertEqual(manifest["output_format"], "cbz")
            self.assertEqual(manifest["artifact"]["path"], "document.cbz")

    def test_wrong_expected_count_stops_before_download(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--expected",
                    "6",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((Path(temp) / "pages.json").exists())
            self.assertFalse((Path(temp) / "images").exists())
            work_images = Path(temp) / ".komaforge-work" / "images"
            self.assertTrue(work_images.is_dir())
            self.assertEqual(list(work_images.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
