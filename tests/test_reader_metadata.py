from __future__ import annotations

import unittest

from document_extractor.engine import (
    _page_count_candidates as legacy_page_count_candidates,
)
from document_extractor.engine import (
    _remember_browser_document as legacy_remember_browser_document,
)
from document_extractor.reader_metadata import (
    page_count_candidates,
    reader_publication_total,
    remember_browser_document,
    remember_reader_metadata,
)


class ReaderMetadataTests(unittest.TestCase):
    def test_engine_keeps_historical_observer_imports(self):
        self.assertIs(legacy_page_count_candidates, page_count_candidates)
        self.assertIs(legacy_remember_browser_document, remember_browser_document)

    def test_document_observer_records_pdf_once_for_its_owner_page(self):
        owner_page = object()
        frame = type("Frame", (), {"page": owner_page})()
        request = type(
            "Request",
            (),
            {"method": "GET", "frame": frame},
        )()
        response = type(
            "Response",
            (),
            {
                "request": request,
                "headers": {
                    "content-type": "application/pdf",
                    "content-length": "2048",
                    "accept-ranges": "bytes",
                },
            },
        )()
        candidates: list[dict] = []

        remember_browser_document(candidates, response)
        remember_browser_document(candidates, response)

        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0]["owner_page"], owner_page)
        self.assertEqual(candidates[0]["document_format"], "pdf")
        self.assertEqual(candidates[0]["content_length"], 2048)

    def test_json_observer_and_nested_metadata_produce_expected_total(self):
        owner_page = object()
        frame = type("Frame", (), {"page": owner_page})()
        request = type(
            "Request",
            (),
            {"method": "GET", "frame": frame},
        )()

        class FakeResponse:
            headers = {"content-type": "application/json; charset=utf-8"}
            url = "https://reader.example.test/page-labels"

            def __init__(self):
                self.request = request

            def json(self):
                return {
                    "publication": {
                        "totalPages": 3,
                        "labels": ["i", "ii", "1"],
                    }
                }

        candidates: list[dict] = []
        remember_reader_metadata(candidates, FakeResponse())

        total = reader_publication_total(object(), candidates, owner_page)

        self.assertIsNotNone(total)
        self.assertEqual(total.value, 3)
        self.assertIn("page-labels", total.source)
        self.assertEqual(total.confidence, "élevée")

    def test_page_count_parser_rejects_boolean_and_implausible_values(self):
        found = page_count_candidates(
            {
                "pageCount": True,
                "totalPages": 100_001,
                "nested": {"numberOfPages": 42},
            },
            "/metadata",
        )

        self.assertEqual([item["value"] for item in found], [42])


if __name__ == "__main__":
    unittest.main()
