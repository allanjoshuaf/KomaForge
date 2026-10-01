from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from document_extractor.engine import download_pages as legacy_download_pages
from document_extractor.engine import host_is_allowed as legacy_host_is_allowed
from document_extractor.page_download import download_pages, host_is_allowed
from tests.mock_site import PNG


class PageDownloadTests(unittest.TestCase):
    def test_engine_keeps_historical_download_imports(self):
        self.assertIs(legacy_download_pages, download_pages)
        self.assertIs(legacy_host_is_allowed, host_is_allowed)

    def test_embedded_page_bypasses_network_and_private_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            images = Path(temp)
            results, missing = download_pages(
                context=None,
                pages=[
                    {
                        "page": 1,
                        "url": "browser-blob:page-1",
                        "_embedded_data": PNG,
                        "_embedded_content_type": "image/png",
                    }
                ],
                images_dir=images,
                source_url="https://reader.example.test/book",
                allowed_hosts={"reader.example.test"},
                retries=1,
                max_image_bytes=1024 * 1024,
                watermark_policy="keep",
                watermark_texts=[],
            )

            self.assertEqual(missing, [])
            self.assertEqual(results[0]["file"], "page-0001.png")
            self.assertNotIn("_embedded_data", results[0])
            self.assertEqual((images / "page-0001.png").read_bytes(), PNG)

    def test_untrusted_remote_page_is_blocked_without_network_access(self):
        with tempfile.TemporaryDirectory() as temp:
            results, missing = download_pages(
                context=None,
                pages=[{"page": 7, "url": "https://ads.example.test/banner.png"}],
                images_dir=Path(temp),
                source_url="https://reader.example.test/book",
                allowed_hosts={"reader.example.test"},
                retries=1,
                max_image_bytes=1024 * 1024,
                watermark_policy="keep",
                watermark_texts=[],
            )

            self.assertEqual(results, [])
            self.assertEqual(missing, [7])


if __name__ == "__main__":
    unittest.main()
