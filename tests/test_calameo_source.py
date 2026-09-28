from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.engine import _chapter_tasks_from_publication
from document_extractor.models import (
    Confidence,
    CoverageStatus,
    PartKind,
    ResourceKind,
)
from document_extractor.providers import build_calameo_pages
from document_extractor.sources import (
    CalameoSource,
    MatchContext,
    SourceReference,
    SourceSession,
    build_default_registry,
)
from document_extractor.sources.calameo import publication_from_provider


SOURCE_URL = "https://www.calameo.com/read/abc_123"


def provider_discovery():
    return build_calameo_pages(
        {
            "key": "book-key",
            "name": "Mon livre de test",
            "document": {"pages": 3},
            "domains": {
                "secured": {"svg": "https://ps.calameoassets.com/"}
            },
        },
        ["https://ps.calameoassets.com/book-key/p1.svgz?token=signed"],
        SOURCE_URL,
    )


class CalameoSourceTests(unittest.TestCase):
    def test_default_registry_claims_calameo_but_not_an_unknown_site(self):
        registry = build_default_registry()

        resolution = registry.resolve(SOURCE_URL)

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.adapter.id, "calameo")
        self.assertEqual(resolution.match.confidence, Confidence.HIGH)
        self.assertIsNone(registry.resolve("https://example.test/read/abc_123"))

    def test_legacy_provider_result_is_normalized_without_losing_pages(self):
        publication = publication_from_provider(provider_discovery(), SOURCE_URL)

        self.assertEqual(publication.source_id, "calameo")
        self.assertEqual(publication.title, "Mon livre de test")
        self.assertEqual(publication.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(publication.coverage.available, 3)
        self.assertEqual(publication.coverage.expected, 3)
        self.assertEqual(len(publication.parts), 1)
        part = publication.parts[0]
        self.assertEqual(part.kind, PartKind.DOCUMENT)
        self.assertEqual(part.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(
            [resource.kind for resource in part.resources],
            [ResourceKind.SVG] * 3,
        )
        self.assertEqual(
            [resource.position for resource in part.resources],
            [1, 2, 3],
        )

    def test_normalized_publication_drives_core_download_tasks(self):
        publication = publication_from_provider(provider_discovery(), SOURCE_URL)

        tasks = _chapter_tasks_from_publication(publication)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, "book")
        self.assertEqual(tasks[0].expected.value, 3)
        self.assertEqual(tasks[0].expected.confidence, "élevée")
        self.assertEqual(
            [page["url"] for page in tasks[0].pages],
            [resource.locator for resource in publication.parts[0].resources],
        )

    @patch("document_extractor.sources.calameo.discover_provider")
    def test_adapter_uses_the_existing_proven_provider_inspection(
        self,
        discover_provider_mock,
    ):
        discover_provider_mock.return_value = provider_discovery()
        source = CalameoSource()
        reference = SourceReference("calameo", SOURCE_URL, SOURCE_URL)
        session = SourceSession(browser_context=object(), page=object())

        publication = source.get_publication(reference, session)
        parts = source.get_parts(publication, session)
        resources = source.get_resources(parts[0], session)

        self.assertEqual(resources.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(len(resources.resources), 3)
        discover_provider_mock.assert_called_once_with(
            session.browser_context,
            session.page,
            SOURCE_URL,
        )


if __name__ == "__main__":
    unittest.main()
