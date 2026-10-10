from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.reader_families import (
    BUILTIN_RESOURCE_STRATEGIES,
    discover_resource_pages,
    resolve_reader_resources,
)
from document_extractor.sources.catalog import BUILTIN_READER_FAMILIES


class FakeLocator:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class FakePage:
    def __init__(self, document_images: int = 0) -> None:
        self.document_images = document_images

    def locator(self, selector: str) -> FakeLocator:
        if selector == "img[data-document-page]":
            return FakeLocator(self.document_images)
        return FakeLocator()


class ReaderFamilyTests(unittest.TestCase):
    def test_strategy_identifiers_are_unique_and_use_catalog_families(self):
        strategy_ids = [item.strategy_id for item in BUILTIN_RESOURCE_STRATEGIES]
        family_ids = {item.family_id for item in BUILTIN_RESOURCE_STRATEGIES}
        catalog_family_ids = {item.id for item in BUILTIN_READER_FAMILIES}

        self.assertEqual(len(strategy_ids), len(set(strategy_ids)))
        self.assertEqual(family_ids, {"paginated-images", "vertical-images"})
        self.assertTrue(family_ids <= catalog_family_ids)

    @patch(
        "document_extractor.detection.pages_from_manifest",
        return_value=[
            {
                "page": 7,
                "url": "https://example.test/seven.webp",
                "source": "html-manifest",
            }
        ],
    )
    def test_html_manifest_keeps_its_declared_page_number(self, _manifest):
        pages, evidence = discover_resource_pages(FakePage(), None, expected=1)

        self.assertEqual(pages[0]["page"], 7)
        self.assertEqual(evidence, "html-manifest")

    @patch("document_extractor.detection.pages_from_manifest", return_value=[])
    @patch("document_extractor.detection.normalize_selector_input", return_value=None)
    @patch(
        "document_extractor.detection.collect_virtual_blob_reader_candidates",
        return_value=[{"position": 1, "url": "blob:https://example.test/one"}],
    )
    @patch("document_extractor.detection.collect_chapter_reader_manifest")
    def test_first_matching_family_stops_later_detection(
        self,
        chapter_manifest,
        _virtual_blob,
        _normalize_selector,
        _manifest,
    ):
        match = resolve_reader_resources(FakePage(), None, expected=1)

        self.assertEqual(match.family_id, "vertical-images")
        self.assertEqual(match.strategy_id, "virtual-blob")
        chapter_manifest.assert_not_called()

    @patch("document_extractor.detection.pages_from_manifest", return_value=[])
    @patch("document_extractor.detection.normalize_selector_input", return_value="img.page")
    @patch(
        "document_extractor.detection.collect_image_candidates",
        return_value=[
            {"position": 2, "url": "https://example.test/two.webp"},
            {"position": 1, "url": "https://example.test/one.webp"},
        ],
    )
    def test_explicit_selector_precedes_automatic_families(
        self,
        _collect_images,
        _normalize_selector,
        _manifest,
    ):
        match = resolve_reader_resources(FakePage(), "img.page", expected=2)

        self.assertEqual(match.strategy_id, "explicit-selector")
        self.assertEqual(
            [item["url"] for item in match.items],
            [
                "https://example.test/one.webp",
                "https://example.test/two.webp",
            ],
        )


if __name__ == "__main__":
    unittest.main()
