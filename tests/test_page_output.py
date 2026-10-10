from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_extractor.page_output import produce_page_document


class PageOutputTests(unittest.TestCase):
    def test_complete_pages_authorize_selected_cdn_and_create_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captured_hosts = set()

            def download(**kwargs):
                captured_hosts.update(kwargs["allowed_hosts"])
                return (
                    [
                        {"file": "page-0001.jpg", "watermarks_removed": 0},
                        {"file": "page-0002.jpg", "watermarks_removed": 0},
                    ],
                    [],
                )

            def create_output(
                _format,
                files,
                output_dir,
                _title,
                **_kwargs,
            ):
                self.assertEqual(
                    files,
                    [
                        root / "images" / "page-0001.jpg",
                        root / "images" / "page-0002.jpg",
                    ],
                )
                artifact = output_dir / "chapter.cbz"
                artifact.write_bytes(b"archive")
                return artifact

            with (
                patch(
                    "document_extractor.page_output.trusted_selected_resource_hosts",
                    return_value={"cdn.example.test": 2},
                ),
                patch(
                    "document_extractor.page_output.download_pages",
                    side_effect=download,
                ),
                patch(
                    "document_extractor.page_output.create_selected_output",
                    side_effect=create_output,
                ),
            ):
                result = produce_page_document(
                    context=object(),
                    pages=[{"url": "https://cdn.example.test/1.jpg"}],
                    images_dir=root / "images",
                    artifact_dir=root / "out",
                    source_url="https://reader.example.test/book",
                    page_url="https://reader.example.test/book",
                    allowed_hosts={"source.example.test"},
                    retries=2,
                    max_image_bytes=1024,
                    watermark_policy="keep",
                    watermark_texts=[],
                    workers=2,
                    selected_output_format="cbz",
                    title="Chapter",
                    chrome_executable=Path("chrome.exe"),
                    output_stem="chapter",
                )

            self.assertEqual(
                captured_hosts,
                {
                    "source.example.test",
                    "reader.example.test",
                    "cdn.example.test",
                },
            )
            self.assertEqual(result.artifact.read_bytes(), b"archive")
            self.assertEqual(result.missing, [])
            self.assertEqual(result.quality, "original page bytes preserved; no resize")

    def test_missing_pages_stop_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch(
                    "document_extractor.page_output.trusted_selected_resource_hosts",
                    return_value={},
                ),
                patch(
                    "document_extractor.page_output.download_pages",
                    return_value=(
                        [{"file": "page-0001.svg", "watermarks_removed": 1}],
                        [2],
                    ),
                ),
                patch(
                    "document_extractor.page_output.create_selected_output"
                ) as create_output,
            ):
                result = produce_page_document(
                    context=object(),
                    pages=[{"url": "browser-blob:page-1"}],
                    images_dir=root / "images",
                    artifact_dir=root / "out",
                    source_url="https://reader.example.test/book",
                    page_url="https://reader.example.test/book",
                    allowed_hosts=set(),
                    retries=1,
                    max_image_bytes=1024,
                    watermark_policy="remove-exact-text",
                    watermark_texts=["sample"],
                    workers=1,
                    selected_output_format="cbz",
                    title="Chapter",
                    chrome_executable=Path("chrome.exe"),
                    output_stem="chapter",
                )

            create_output.assert_not_called()
            self.assertIsNone(result.artifact)
            self.assertEqual(result.missing, [2])
            self.assertEqual(result.watermarks_removed, 1)
            self.assertIn("watermark", result.quality)


if __name__ == "__main__":
    unittest.main()
