from __future__ import annotations

import unittest

from document_extractor.legacy_bridge import (
    LegacyManifestError,
    normalize_legacy_manifest,
)
from document_extractor.models import CoverageStatus, PartKind


def manifest(record: dict, *, availability: dict | None = None) -> dict:
    publication = {
        "type": "document",
        "title": "Example",
        "part_count": 1,
        "selected_part_count": 1,
        "chapters": [record],
        "status": "complete" if record.get("status") != "incomplete" else "incomplete",
    }
    if availability is not None:
        publication["availability"] = availability
    return {
        "source_url": "https://example.test/book",
        "publication": publication,
    }


class LegacyBridgeTests(unittest.TestCase):
    def test_interstitial_title_is_recovered_from_the_stable_source_url(self):
        data = manifest(
            {
                "index": 1,
                "number": "1",
                "title": "Just a moment",
                "kind": "document",
                "source_url": "https://sushiscan.net/chainsaw-man-volume-1/",
                "status": "complete",
                "detected": 1,
                "expected": 1,
            }
        )
        data["source_url"] = "https://sushiscan.net/chainsaw-man-volume-1/"
        data["publication"]["title"] = "Just a moment"

        work = normalize_legacy_manifest(data, "generic-web")

        self.assertEqual(work.title, "Chainsaw Man Volume 1")
        self.assertEqual(work.publications[0].title, "Chainsaw Man Volume 1")

    def test_flat_historical_manifest_uses_its_directory_title_hint(self):
        work = normalize_legacy_manifest(
            {
                "source_url": "https://example.test/old-book",
                "expected": 1,
                "detected": 1,
                "missing": [],
                "pages": [
                    {
                        "page": 1,
                        "url": "https://cdn.example.test/1.webp?_token_=secret",
                        "file": "page-0001.webp",
                    }
                ],
            },
            "generic-web",
            title_hint="Old Book",
        )

        publication = work.publications[0]
        self.assertEqual(publication.title, "Old Book")
        self.assertEqual(publication.metadata["legacy_status"], "complete")
        self.assertTrue(publication.parts[0].resources[0].sensitive_locator)

    def test_flat_historical_manifest_without_title_hint_is_rejected(self):
        with self.assertRaisesRegex(LegacyManifestError, "title hint"):
            normalize_legacy_manifest(
                {
                    "source_url": "https://example.test/old-book",
                    "expected": 0,
                    "detected": 0,
                    "pages": [],
                },
                "generic-web",
            )

    def test_complete_image_record_becomes_normalized_models(self):
        work = normalize_legacy_manifest(
            manifest(
                {
                    "index": 1,
                    "number": "1",
                    "title": "Example",
                    "kind": "document",
                    "source_url": "https://example.test/book",
                    "status": "complete",
                    "detected": 2,
                    "expected": 2,
                    "expected_source": "manifest",
                    "resource_unit": "source_image",
                    "pages": [
                        {
                            "page": 1,
                            "url": "https://cdn.example.test/1.webp",
                            "file": "page-0001.webp",
                            "sha256": "a" * 64,
                        },
                        {
                            "page": 2,
                            "url": "https://cdn.example.test/2.svgz",
                            "file": "page-0002.svg",
                            "sha256": "b" * 64,
                        },
                    ],
                }
            ),
            "generic-web",
        )

        publication = work.publications[0]
        self.assertEqual(publication.source_id, "generic-web")
        self.assertEqual(publication.parts[0].kind, PartKind.DOCUMENT)
        self.assertEqual(publication.parts[0].coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(len(publication.parts[0].resources), 2)

    def test_incomplete_epub_coverage_is_not_upgraded(self):
        work = normalize_legacy_manifest(
            manifest(
                {
                    "index": 1,
                    "number": "1",
                    "title": "Example",
                    "kind": "document",
                    "source_url": "https://example.test/book",
                    "status": "incomplete",
                    "detected": 11,
                    "expected": 62,
                    "expected_source": "EPUB navigation document",
                    "resource_unit": "epub_document",
                }
            ),
            "ebooks",
        )

        coverage = work.publications[0].parts[0].coverage
        self.assertEqual(coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(coverage.missing, 51)
        publication_coverage = work.publications[0].coverage
        self.assertEqual(publication_coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(publication_coverage.missing, 51)

    def test_single_document_inherits_top_level_coverage_diagnostics(self):
        data = manifest(
            {
                "index": 1,
                "number": "1",
                "title": "Example",
                "kind": "document",
                "source_url": "https://example.test/book",
                "status": "incomplete",
                "page_count": 11,
            }
        )
        data.update(
            {
                "detected": 11,
                "expected": 62,
                "expected_source": "EPUB navigation document",
                "resource_unit": "epub_document",
            }
        )

        work = normalize_legacy_manifest(data, "ebooks")

        coverage = work.publications[0].parts[0].coverage
        self.assertEqual(coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(coverage.available, 11)
        self.assertEqual(coverage.expected, 62)

    def test_incomplete_publication_with_unknown_total_never_claims_complete(self):
        work = normalize_legacy_manifest(
            manifest(
                {
                    "index": 1,
                    "number": "1",
                    "title": "Example",
                    "kind": "document",
                    "source_url": "https://example.test/book",
                    "status": "incomplete",
                    "detected": 2,
                    "expected": None,
                    "pages": [
                        {"page": 1, "url": "https://example.test/1.webp"},
                        {"page": 2, "url": "https://example.test/2.webp"},
                    ],
                }
            ),
            "generic-web",
        )

        self.assertEqual(
            work.publications[0].coverage.status,
            CoverageStatus.UNKNOWN,
        )

    def test_source_limited_catalog_remains_distinct(self):
        data = manifest(
            {
                "index": 1,
                "number": "1 -1",
                "title": "Chapter 1 -1",
                "kind": "segment",
                "source_url": "https://global.manga-up.com/manga/126/1",
                "status": "inspected",
                "detected": 19,
                "expected": 19,
            },
            availability={
                "catalog_part_count": 288,
                "accessible_part_count": 3,
                "access_limited": True,
                "source": "public catalog",
            },
        )
        data["publication"]["status"] = "limited_by_source"

        work = normalize_legacy_manifest(data, "manga-up")

        self.assertEqual(
            work.publications[0].coverage.status,
            CoverageStatus.SOURCE_LIMITED,
        )

    def test_contradictory_complete_record_is_rejected(self):
        with self.assertRaisesRegex(LegacyManifestError, "claims complete"):
            normalize_legacy_manifest(
                manifest(
                    {
                        "index": 1,
                        "number": "1",
                        "title": "Example",
                        "kind": "document",
                        "source_url": "https://example.test/book",
                        "status": "complete",
                        "detected": 2,
                        "expected": 3,
                    }
                ),
                "generic-web",
            )


if __name__ == "__main__":
    unittest.main()
