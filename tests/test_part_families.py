from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.detection import ChapterLink, SelectablePart
from document_extractor.models import Coverage, PartKind, Publication
from document_extractor.part_families import (
    BUILTIN_PART_STRATEGIES,
    discover_part_candidates,
)
from document_extractor.sources.catalog import BUILTIN_READER_FAMILIES


def publication(url: str = "https://example.test/work") -> Publication:
    return Publication(
        id="publication-one",
        work_id="work-one",
        source_id="generic-web",
        title="One",
        source_url=url,
        coverage=Coverage.from_counts(0, None, unit="resources"),
    )


class PartFamilyTests(unittest.TestCase):
    def test_strategies_use_declared_catalog_families(self):
        family_ids = {family.id for family in BUILTIN_READER_FAMILIES}
        strategy_ids = [strategy.strategy_id for strategy in BUILTIN_PART_STRATEGIES]

        self.assertTrue(
            all(strategy.family_id in family_ids for strategy in BUILTIN_PART_STRATEGIES)
        )
        self.assertEqual(len(strategy_ids), len(set(strategy_ids)))

    @patch(
        "document_extractor.detection.discover_chapters",
        return_value=[
            ChapterLink(1, "1", "Chapter 1", "https://example.test/chapter-1"),
            ChapterLink(2, "2", "Chapter 2", "https://example.test/chapter-2"),
            ChapterLink(3, "3", "Chapter 3", "https://example.test/chapter-3"),
        ],
    )
    def test_linked_chapters_win_before_select_controls(self, _discover_chapters):
        result = discover_part_candidates(object(), publication(), {})

        self.assertEqual(result.strategy_id, "linked-chapters")
        self.assertEqual([item.number for item in result.candidates], ["1", "2", "3"])

    @patch("document_extractor.detection.discover_chapters", return_value=[])
    @patch(
        "document_extractor.detection.discover_selectable_parts",
        return_value=[
            SelectablePart(1, "1", "Volume 1", "volume", "select#volume", "v1"),
            SelectablePart(2, "2", "Volume 2", "volume", "select#volume", "v2"),
        ],
    )
    def test_select_control_preserves_runtime_selection_metadata(
        self,
        _selectable,
        _chapters,
    ):
        result = discover_part_candidates(object(), publication(), {})

        self.assertEqual(result.strategy_id, "select-control")
        self.assertEqual(result.candidates[0].kind, PartKind.VOLUME)
        self.assertEqual(
            result.candidates[0].metadata,
            {"selection_selector": "select#volume", "selection_value": "v1"},
        )

    @patch("document_extractor.detection.discover_selectable_parts", return_value=[])
    def test_chapter_url_falls_back_to_one_numbered_part(self, _selectable):
        result = discover_part_candidates(
            object(),
            publication("https://example.test/manga/chapter-12.5"),
            {},
        )

        self.assertEqual(result.strategy_id, "single-document")
        self.assertEqual(result.candidates[0].kind, PartKind.CHAPTER)
        self.assertEqual(result.candidates[0].number, "12.5")


if __name__ == "__main__":
    unittest.main()
