from __future__ import annotations

import unittest

from document_extractor.models import (
    Confidence,
    Coverage,
    CoverageStatus,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
    Work,
)


class CoverageTests(unittest.TestCase):
    def test_complete_coverage_requires_matching_counts(self):
        coverage = Coverage(
            status=CoverageStatus.COMPLETE,
            available=144,
            expected=144,
            unit="pages",
            evidence="public manifest",
            confidence=Confidence.HIGH,
        )

        self.assertTrue(coverage.is_complete)
        self.assertEqual(coverage.missing, 0)

        with self.assertRaisesRegex(ValueError, "available == expected"):
            Coverage(
                status=CoverageStatus.COMPLETE,
                available=11,
                expected=62,
                unit="sections",
            )

    def test_incomplete_coverage_preserves_the_missing_count(self):
        coverage = Coverage.from_counts(
            11,
            62,
            unit="sections",
            evidence="EPUB navigation document",
            confidence=Confidence.HIGH,
        )

        self.assertEqual(coverage.status, CoverageStatus.INCOMPLETE)
        self.assertEqual(coverage.missing, 51)
        self.assertEqual(coverage.to_manifest()["missing"], 51)

    def test_source_limited_is_distinct_from_an_accidental_failure(self):
        coverage = Coverage.from_counts(
            3,
            288,
            unit="segments",
            evidence="public catalog",
            source_limited=True,
        )

        self.assertEqual(coverage.status, CoverageStatus.SOURCE_LIMITED)
        self.assertEqual(coverage.missing, 285)

    def test_unknown_total_never_claims_completion(self):
        coverage = Coverage.from_counts(12, None, unit="resources")

        self.assertEqual(coverage.status, CoverageStatus.UNKNOWN)
        self.assertIsNone(coverage.missing)

    def test_negative_or_impossible_counts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "negative"):
            Coverage(CoverageStatus.UNKNOWN, -1)
        with self.assertRaisesRegex(ValueError, "exceed"):
            Coverage(CoverageStatus.UNKNOWN, 4, expected=3)
        with self.assertRaisesRegex(ValueError, "requires an expected total"):
            Coverage(CoverageStatus.INCOMPLETE, 4)


class DomainModelTests(unittest.TestCase):
    def _work(self) -> Work:
        resources = (
            Resource(
                id="page-1",
                kind=ResourceKind.IMAGE,
                locator="https://cdn.example.test/page-1.webp",
                position=1,
                media_type="image/webp",
            ),
            Resource(
                id="page-2",
                kind=ResourceKind.SVG,
                locator="https://cdn.example.test/page-2.svgz",
                position=2,
                media_type="image/svg+xml",
            ),
        )
        part = Part(
            id="chapter-1",
            kind=PartKind.CHAPTER,
            title="Chapter 1",
            position=1,
            number="1",
            source_url="https://example.test/work/chapter-1",
            resources=resources,
            coverage=Coverage.from_counts(2, 2, unit="resources"),
        )
        publication = Publication(
            id="example-edition",
            work_id="example-work",
            source_id="example-source",
            title="Example Work",
            source_url="https://example.test/work",
            parts=(part,),
            coverage=Coverage.from_counts(1, 1, unit="parts"),
        )
        return Work(
            id="example-work",
            title="Example Work",
            publications=(publication,),
            authors=("Author",),
            genres=("Adventure",),
        )

    def test_full_model_serializes_to_a_manifest_ready_dictionary(self):
        manifest = self._work().to_manifest()

        self.assertEqual(manifest["id"], "example-work")
        publication = manifest["publications"][0]
        self.assertEqual(publication["coverage"]["status"], "complete")
        part = publication["parts"][0]
        self.assertEqual(part["kind"], "chapter")
        self.assertEqual(
            [resource["kind"] for resource in part["resources"]],
            ["image", "svg"],
        )

    def test_publication_must_belong_to_its_containing_work(self):
        publication = Publication(
            id="edition",
            work_id="another-work",
            source_id="example-source",
            title="Example Work",
            source_url="https://example.test/work",
        )

        with self.assertRaisesRegex(ValueError, "work_id"):
            Work(
                id="example-work",
                title="Example Work",
                publications=(publication,),
            )

    def test_duplicate_positions_are_rejected(self):
        first = Resource("one", ResourceKind.IMAGE, "https://example.test/1", 1)
        second = Resource("two", ResourceKind.IMAGE, "https://example.test/2", 1)

        with self.assertRaisesRegex(ValueError, "positions must be unique"):
            Part(
                id="chapter",
                kind=PartKind.CHAPTER,
                title="Chapter",
                position=1,
                source_url="https://example.test/chapter",
                resources=(first, second),
            )


if __name__ == "__main__":
    unittest.main()
