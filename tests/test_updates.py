from __future__ import annotations

import unittest

from document_extractor.models import Coverage, Part, PartKind, Publication
from document_extractor.updates import compare_part_updates


def part(part_id: str, url: str, number: str) -> Part:
    return Part(
        id=part_id,
        kind=PartKind.CHAPTER,
        title=f"Chapter {number}",
        position=int(number),
        number=number,
        source_url=url,
    )


class UpdateComparisonTests(unittest.TestCase):
    def test_detects_only_new_parts_despite_different_internal_ids(self):
        known = (
            part("legacy-one", "https://example.test/chapter/1?utm_source=old", "1"),
        )
        current = (
            part("current-one", "https://example.test/chapter/1", "1"),
            part("current-two", "https://example.test/chapter/2", "2"),
        )
        publication = Publication(
            id="publication",
            work_id="work",
            source_id="generic-web",
            title="Example",
            source_url="https://example.test/work",
            parts=current,
            coverage=Coverage.from_counts(2, 2, unit="parts"),
        )

        result = compare_part_updates(publication, known, current)

        self.assertEqual([item.number for item in result.parts], ["2"])
        self.assertTrue(result.coverage.is_complete)

    def test_source_limited_coverage_is_not_upgraded(self):
        current = (part("one", "https://example.test/chapter/1", "1"),)
        publication = Publication(
            id="publication",
            work_id="work",
            source_id="manga-up",
            title="Example",
            source_url="https://example.test/work",
            parts=current,
            coverage=Coverage.from_counts(
                1,
                10,
                unit="parts",
                source_limited=True,
            ),
        )

        result = compare_part_updates(publication, (), current)

        self.assertEqual(result.coverage.status.value, "source_limited")
        self.assertEqual(len(result.parts), 1)


if __name__ == "__main__":
    unittest.main()
