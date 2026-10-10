from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from document_extractor.detection import ChapterLink, ExpectedCount
from document_extractor.models import CoverageStatus, PartKind, ResourceKind
from document_extractor.sources import (
    GenericWebSource,
    MatchContext,
    SourceReference,
    SourceRegistry,
    SourceSession,
)


class FakePage:
    url = "https://example.test/work"

    @staticmethod
    def title() -> str:
        return "Example Work | Reader"


class GenericWebSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = GenericWebSource()
        self.session = SourceSession(page=FakePage(), options={"activate_reader": False})
        self.reference = SourceReference(
            source_id="generic-web",
            value="https://example.test/work",
            url="https://example.test/work",
        )

    def test_generic_source_is_an_explicit_fallback_not_a_registry_default(self):
        self.assertIsNone(SourceRegistry().resolve("https://example.test/work"))
        self.assertTrue(
            self.source.match("https://example.test/work", MatchContext()).matched
        )
        self.assertFalse(
            self.source.match("file:///tmp/book.pdf", MatchContext()).matched
        )

    def test_publication_uses_a_stable_identity_and_clean_title(self):
        first = self.source.get_publication(self.reference, self.session)
        second = self.source.get_publication(self.reference, self.session)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.work_id, second.work_id)
        self.assertEqual(first.source_id, "generic-web")
        self.assertEqual(first.title, "Example Work | Reader")

    @patch("document_extractor.detection.discover_selectable_parts", return_value=[])
    @patch("document_extractor.detection.discover_chapters")
    def test_chapter_discovery_becomes_normalized_parts(
        self,
        discover_chapters_mock,
        _discover_selectable_parts_mock,
    ):
        discover_chapters_mock.return_value = [
            ChapterLink(1, "1", "Chapter 1", "https://example.test/chapter-1"),
            ChapterLink(2, "2", "Chapter 2", "https://example.test/chapter-2"),
            ChapterLink(3, "3", "Chapter 3", "https://example.test/chapter-3"),
        ]
        publication = self.source.get_publication(self.reference, self.session)

        parts = self.source.get_parts(publication, self.session)

        self.assertEqual([part.kind for part in parts], [PartKind.CHAPTER] * 3)
        self.assertEqual([part.number for part in parts], ["1", "2", "3"])
        self.assertTrue(all(part.coverage.expected is None for part in parts))

    @patch("document_extractor.sources.generic.discover_pages")
    @patch("document_extractor.sources.generic.hydrate_lazy_content")
    @patch("document_extractor.sources.generic.detect_expected_count")
    @patch("document_extractor.detection.discover_selectable_parts", return_value=[])
    @patch("document_extractor.detection.discover_chapters", return_value=[])
    def test_resource_detection_preserves_incomplete_coverage(
        self,
        _discover_chapters_mock,
        _discover_selectable_parts_mock,
        detect_expected_count_mock,
        _hydrate_lazy_content_mock,
        discover_pages_mock,
    ):
        detect_expected_count_mock.return_value = ExpectedCount(
            3,
            "reader metadata",
            "élevée",
        )
        discover_pages_mock.return_value = (
            [
                {"page": 1, "url": "https://example.test/1.webp", "source": "img"},
                {"page": 2, "url": "https://example.test/2.svgz", "source": "img"},
            ],
            "img.page",
        )
        publication = self.source.get_publication(self.reference, self.session)
        part = self.source.get_parts(publication, self.session)[0]

        result = self.source.get_resources(part, self.session)

        self.assertEqual(result.coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(result.coverage.missing, 1)
        self.assertEqual(
            [resource.kind for resource in result.resources],
            [ResourceKind.IMAGE, ResourceKind.SVG],
        )
        self.assertEqual(result.resources[0].metadata["source"], "img")

    @patch("document_extractor.sources.generic.discover_pages")
    @patch("document_extractor.sources.generic.hydrate_lazy_content")
    @patch("document_extractor.sources.generic.detect_expected_count")
    @patch("document_extractor.detection.discover_selectable_parts", return_value=[])
    @patch("document_extractor.detection.discover_chapters", return_value=[])
    def test_continuous_sequence_overrides_a_low_confidence_visible_counter(
        self,
        _discover_chapters_mock,
        _discover_selectable_parts_mock,
        detect_expected_count_mock,
        _hydrate_lazy_content_mock,
        discover_pages_mock,
    ):
        detect_expected_count_mock.return_value = ExpectedCount(
            2,
            "visible reader counter",
            "moyenne",
        )
        discover_pages_mock.return_value = (
            [
                {
                    "page": position + 1,
                    "document_index": position,
                    "url": f"https://example.test/{position + 1}.webp",
                }
                for position in range(3)
            ],
            "img.page",
        )
        publication = self.source.get_publication(self.reference, self.session)
        part = self.source.get_parts(publication, self.session)[0]

        result = self.source.get_resources(part, self.session)

        self.assertEqual(result.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(result.coverage.available, 3)
        self.assertEqual(result.coverage.expected, 3)
        self.assertEqual(result.coverage.evidence, "continuous data-index sequence")


if __name__ == "__main__":
    unittest.main()
