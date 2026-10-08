from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_extractor.document_output import (
    produce_epub_document,
    produce_pdf_document,
)


class DocumentOutputTests(unittest.TestCase):
    def test_native_pdf_preserves_original_bytes(self):
        payload = b"%PDF-1.7\nvalidated"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = produce_pdf_document(
                data=payload,
                page_count=12,
                selected_output_format="pdf",
                artifact_dir=root / "out",
                output_stem="document",
                title="Document",
                chrome_executable=Path("chrome.exe"),
            )

            self.assertEqual(result.artifact.read_bytes(), payload)
            self.assertEqual(result.saved, 12)
            self.assertEqual(result.resource_unit, "pdf_document")
            self.assertIsNone(result.render_dpi)
            self.assertEqual(
                result.source_sha256,
                hashlib.sha256(payload).hexdigest(),
            )

    def test_pdf_conversion_reports_rendered_pages(self):
        payload = b"%PDF-1.7\nvalidated"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rendered_page = root / "images" / "page-0001.png"
            rendered_page.parent.mkdir(parents=True)
            rendered_page.write_bytes(b"png")

            def create_output(
                _format,
                _files,
                output_dir,
                _title,
                **_kwargs,
            ):
                artifact = output_dir / "document.cbz"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b"archive")
                return artifact

            with (
                patch(
                    "document_extractor.document_output.render_pdf_bytes_to_images",
                    return_value=[rendered_page],
                ) as render,
                patch(
                    "document_extractor.document_output.create_selected_output",
                    side_effect=create_output,
                ),
            ):
                result = produce_pdf_document(
                    data=payload,
                    page_count=1,
                    selected_output_format="cbz",
                    artifact_dir=root / "out",
                    output_stem="document",
                    title="Document",
                    chrome_executable=Path("chrome.exe"),
                    images_dir=root / "images",
                )

            render.assert_called_once_with(payload, root / "images", dpi=200)
            self.assertEqual(result.artifact.read_bytes(), b"archive")
            self.assertEqual(result.resource_unit, "rendered_pdf_page")
            self.assertEqual(result.render_dpi, 200)

    def test_native_epub_preserves_original_bytes(self):
        payload = b"validated-epub"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = produce_epub_document(
                data=payload,
                spine_count=8,
                selected_output_format="epub",
                artifact_dir=root / "out",
                output_stem="book",
                title="Book",
                chrome_executable=Path("chrome.exe"),
                converted_pdf=root / "work" / "source-rendered.pdf",
            )

            self.assertEqual(result.artifact.read_bytes(), payload)
            self.assertEqual(result.saved, 8)
            self.assertEqual(result.resource_unit, "epub_document")
            self.assertIsNone(result.detected)

    def test_epub_pdf_conversion_moves_validated_result(self):
        payload = b"validated-epub"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            converted_pdf = root / "work" / "source-rendered.pdf"

            def convert(_data, destination, _chrome):
                destination.write_bytes(b"%PDF-1.7\nconverted")
                return destination, {"page_count": 19}

            with patch(
                "document_extractor.document_output.create_pdf_from_epub_bytes",
                side_effect=convert,
            ):
                result = produce_epub_document(
                    data=payload,
                    spine_count=8,
                    selected_output_format="pdf",
                    artifact_dir=root / "out",
                    output_stem="book",
                    title="Book",
                    chrome_executable=Path("chrome.exe"),
                    converted_pdf=converted_pdf,
                )

            self.assertEqual(result.artifact.read_bytes(), b"%PDF-1.7\nconverted")
            self.assertFalse(converted_pdf.exists())
            self.assertEqual(result.saved, 19)
            self.assertEqual(result.detected, 19)
            self.assertEqual(result.resource_unit, "epub_document")


if __name__ == "__main__":
    unittest.main()
