from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.engine import _chapter_tasks_from_publication
from document_extractor.models import CoverageStatus, ResourceKind
from document_extractor.sources import (
    EBooksSource,
    SourceReference,
    SourceSession,
    build_default_registry,
)


PRODUCT_URL = "https://www.ebooks.com/en-us/book/347114076/the-demon-star/jesse-aragon/"
READER_URL = "https://reader.ebooks.com/preview?uid=session&reqid=request&hash=secret"


class FakePage:
    url = PRODUCT_URL

    @staticmethod
    def title() -> str:
        return "The Demon Star | eBooks.com Reader (Preview)"


class FakeReaderPage:
    url = READER_URL

    @staticmethod
    def title() -> str:
        return "eBooks.com Reader"


class EBooksSourceTests(unittest.TestCase):
    def test_registry_recognizes_product_and_reader_urls(self):
        registry = build_default_registry()

        self.assertEqual(registry.resolve(PRODUCT_URL).adapter.id, "ebooks")
        self.assertEqual(registry.resolve(READER_URL).adapter.id, "ebooks")

    @patch("document_extractor.sources.ebooks.discover_linked_reader")
    def test_product_page_keeps_a_stable_identity_and_session_part(
        self,
        discover_reader_mock,
    ):
        discover_reader_mock.return_value = {
            "url": READER_URL,
            "action": "Preview",
        }
        source = EBooksSource()
        reference = SourceReference("ebooks", PRODUCT_URL, PRODUCT_URL)
        session = SourceSession(browser_context=object(), page=FakePage())

        publication = source.get_publication(reference, session)

        self.assertEqual(publication.source_url, PRODUCT_URL)
        self.assertEqual(publication.title, "The Demon Star")
        self.assertEqual(publication.parts[0].source_url, READER_URL)
        self.assertEqual(publication.parts[0].metadata["reader_action"], "Preview")

        tasks = _chapter_tasks_from_publication(publication)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, "document")
        self.assertEqual(tasks[0].source_url, READER_URL)
        self.assertIsNone(tasks[0].pages)

    def test_session_url_without_product_identity_is_rejected(self):
        source = EBooksSource()
        reference = SourceReference("ebooks", READER_URL, READER_URL)
        session = SourceSession(page=FakePage())

        with self.assertRaisesRegex(RuntimeError, "stable publication identity"):
            source.get_publication(reference, session)

    def test_product_title_survives_navigation_to_a_generic_reader_title(self):
        source = EBooksSource()
        reference = SourceReference("ebooks", READER_URL, READER_URL)
        session = SourceSession(
            page=FakeReaderPage(),
            options={
                "product_url": PRODUCT_URL,
                "title": "The Demon Star by Jesse Aragon (ebook)",
            },
        )

        publication = source.get_publication(reference, session)

        self.assertEqual(publication.title, "The Demon Star")
        self.assertEqual(publication.source_url, PRODUCT_URL)

    @patch("document_extractor.sources.ebooks.discover_linked_reader")
    def test_incomplete_epub_coverage_and_secret_locator_are_preserved_safely(
        self,
        discover_reader_mock,
    ):
        discover_reader_mock.return_value = {"url": READER_URL, "action": "Preview"}
        source = EBooksSource()
        reference = SourceReference("ebooks", PRODUCT_URL, PRODUCT_URL)
        session = SourceSession(
            browser_context=object(),
            page=FakePage(),
            options={
                "document_candidates": [
                    {
                        "owner_page": None,
                        "document_format": "epub",
                        "url": "https://reader-backend.ebooks.com/book.epub?uid=secret",
                        "epub_info": {
                            "spine_item_count": 11,
                            "referenced_document_count": 62,
                            "present_referenced_documents": [
                                f"section-{index}.xhtml" for index in range(11)
                            ],
                        },
                    }
                ]
            },
        )
        publication = source.get_publication(reference, session)

        resources = source.get_resources(publication.parts[0], session)

        self.assertEqual(resources.coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(resources.coverage.available, 11)
        self.assertEqual(resources.coverage.expected, 62)
        self.assertEqual(resources.coverage.missing, 51)
        self.assertEqual(resources.resources[0].kind, ResourceKind.EPUB)
        self.assertIsNone(resources.resources[0].to_manifest()["locator"])

    def test_recognized_reader_without_document_never_uses_generic_fallback(self):
        source = EBooksSource()
        part = unittest.mock.Mock()
        session = SourceSession(page=FakePage(), options={"document_candidates": []})

        with self.assertRaisesRegex(RuntimeError, "fallback is intentionally disabled"):
            source.get_resources(part, session)


if __name__ == "__main__":
    unittest.main()
