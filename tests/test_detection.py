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
from document_extractor.engine import navigate_to_source
from tests.mock_site import MockDocumentHandler


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        _type, error, _traceback = sys.exc_info()
        if isinstance(error, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class SelectorInputTests(unittest.TestCase):
    def test_css_selector_is_unchanged(self):
        self.assertEqual(normalize_selector_input("img.ts-main-image"), "img.ts-main-image")

    def test_html_snippet_is_converted_to_css(self):
        self.assertEqual(
            normalize_selector_input('<img class="ts-main-image lazy" ...>'),
            "img.ts-main-image.lazy",
        )


class FakePage:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.url = "about:blank"
        self.closed = False

    def goto(self, url, **_kwargs):
        self.calls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.url = outcome
        return object()

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, pages):
        self.pages_to_create = list(pages)

    def new_page(self):
        return self.pages_to_create.pop(0)


class NavigationRecoveryTests(unittest.TestCase):
    def test_transient_navigation_error_is_retried_in_a_clean_page(self):
        url = "https://example.test/book"
        failed = FakePage([RuntimeError("net::ERR_CONNECTION_RESET")])
        recovered = FakePage([url])

        result = navigate_to_source(FakeContext([recovered]), failed, url, retries=2)

        self.assertIs(result, recovered)
        self.assertTrue(failed.closed)
        self.assertEqual(recovered.calls, [url])

    def test_ssl_recovery_warms_only_origin_then_reopens_target(self):
        url = "https://www.calameo.com/read/book-id?private=value"
        failed = FakePage([RuntimeError("net::ERR_SSL_PROTOCOL_ERROR")])
        recovered = FakePage(["https://www.calameo.com/", url])

        result = navigate_to_source(FakeContext([recovered]), failed, url)

        self.assertIs(result, recovered)
        self.assertTrue(failed.closed)
        self.assertEqual(
            recovered.calls,
            ["http://www.calameo.com/", url],
        )

    def test_ssl_recovery_rejects_a_redirect_to_another_host(self):
        url = "https://example.test/book"
        failed = FakePage([RuntimeError("net::ERR_SSL_PROTOCOL_ERROR")])
        unsafe = FakePage(["https://different.test/"])

        with self.assertRaisesRegex(RuntimeError, "Impossible d'ouvrir"):
            navigate_to_source(FakeContext([unsafe]), failed, url, retries=1)

        self.assertEqual(unsafe.calls, ["http://example.test/"])


@unittest.skipUnless(os.environ.get("RUN_EXTRACTOR_E2E") == "1", "test navigateur facultatif")
class EndToEndDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = QuietThreadingHTTPServer(("127.0.0.1", 0), MockDocumentHandler)
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

    def test_svgz_detection_and_targeted_watermark_removal(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/svg-document"
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
                    "--format",
                    "images",
                    "--watermarks",
                    "remove",
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = Path(temp)
            pages = sorted((output / "images").glob("page-*.svg"))
            self.assertEqual(len(pages), 2)
            for page in pages:
                data = page.read_bytes()
                self.assertNotIn(b"SPECIMEN", data)
                self.assertIn(b"Page de test", data)
            manifest = json.loads((output / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["watermark_policy"], "remove")
            self.assertEqual(
                [page["watermarks_removed"] for page in manifest["pages"]],
                [1, 1],
            )
            self.assertIn("non compressé", manifest["pages"][0]["normalization"])
            self.assertEqual(manifest["pages"][1]["normalization"], "gzip vers svg")


if __name__ == "__main__":
    unittest.main()
