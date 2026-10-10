from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from document_extractor.reader import ReaderDocument, ReaderServer, build_reader_html


PNG = b"\x89PNG\r\n\x1a\nreader-fixture"


class ReaderDocumentTests(unittest.TestCase):
    def test_image_directory_uses_natural_page_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "page-10.png").write_bytes(PNG)
            (root / "page-2.png").write_bytes(PNG)
            (root / "notes.txt").write_text("ignored", encoding="utf-8")

            document = ReaderDocument.from_path(root)

            self.assertEqual(
                [page.name for page in document.pages],
                ["page-2.png", "page-10.png"],
            )
            self.assertEqual(document.read_page(1), PNG)

    def test_cbz_ignores_unsafe_and_non_image_members(self):
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "book.cbz"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("pages/10.webp", b"ten")
                archive.writestr("pages/2.webp", b"two")
                archive.writestr("../outside.webp", b"unsafe")
                archive.writestr("ComicInfo.xml", b"metadata")

            document = ReaderDocument.from_path(archive_path)

            self.assertEqual(
                [page.name for page in document.pages],
                ["pages/2.webp", "pages/10.webp"],
            )
            self.assertEqual(document.read_page(2), b"ten")

    def test_unsupported_artifact_explains_native_open_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "book.pdf"
            artifact.write_bytes(b"%PDF")

            with self.assertRaisesRegex(ValueError, "library open"):
                ReaderDocument.from_path(artifact)

    def test_reader_markup_includes_accessibility_and_reduced_motion_guards(self):
        markup = build_reader_html(
            title="Book <One>",
            token="secret",
            page_count=2,
            start_position=1,
        ).decode("utf-8")

        self.assertIn("Aller aux pages", markup)
        self.assertIn('aria-label="Commandes de lecture"', markup)
        self.assertIn("prefers-reduced-motion", markup)
        self.assertIn("Book &lt;One&gt;", markup)
        self.assertNotIn("Book <One>", markup)


class ReaderServerTests(unittest.TestCase):
    def test_loopback_server_serves_pages_and_validates_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "page-1.png").write_bytes(PNG)
            (root / "page-2.png").write_bytes(PNG + b"2")
            progress = []
            server = ReaderServer(
                ReaderDocument.from_path(root),
                title="Reader test",
                progress_callback=lambda position, completed: progress.append(
                    (position, completed)
                ),
            )
            thread = threading.Thread(
                target=server.serve,
                kwargs={"open_browser": False},
                daemon=True,
            )
            thread.start()
            try:
                with urlopen(server.url, timeout=5) as response:
                    markup = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    self.assertIn("Reader test", markup)
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

                with urlopen(f"{server.url}page/2", timeout=5) as response:
                    self.assertEqual(response.headers["Content-Type"], "image/png")
                    self.assertEqual(response.read(), PNG + b"2")

                body = json.dumps({"position": 2, "completed": True}).encode("utf-8")
                request = Request(
                    f"{server.url}progress",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 204)
                self.assertEqual(progress, [(2, True)])

                bad = Request(
                    f"{server.url}progress",
                    data=json.dumps({"position": 2, "completed": False}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(bad, timeout=5)
                self.assertEqual(raised.exception.code, 400)

                with self.assertRaises(HTTPError) as raised:
                    urlopen(
                        server.url.replace(f"/{server.token}/", "/unknown/"),
                        timeout=5,
                    )
                self.assertEqual(raised.exception.code, 404)
            finally:
                close = Request(f"{server.url}close", data=b"", method="POST")
                try:
                    urlopen(close, timeout=5).close()
                except OSError:
                    server.shutdown()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
