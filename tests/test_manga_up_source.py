from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.engine import _chapter_tasks_from_publication
from document_extractor.detection import normalize_manga_up_catalog
from document_extractor.models import CoverageStatus, PartKind
from document_extractor.sources import (
    MangaUpSource,
    SourceReference,
    SourceSession,
    UpdateCapability,
    build_default_registry,
)
from document_extractor.sources.manga_up import publication_from_catalog


SOURCE_URL = "https://global.manga-up.com/manga/126"


def catalog():
    result = normalize_manga_up_catalog(
        {
            "props": {
                "pageProps": {
                    "data": {
                        "chapters": [
                            {
                                "id": 10761,
                                "mainName": "Chapter 2 -1",
                                "subName": "The Price of Life",
                                "price": 40,
                            },
                            {
                                "id": 10760,
                                "mainName": "Chapter 1 -3",
                                "subName": "The Two Alchemists",
                                "price": None,
                                "consumptionType": 3,
                            },
                            {
                                "id": 10759,
                                "mainName": "Chapter 1 -2",
                                "subName": "The Two Alchemists",
                                "price": None,
                                "consumptionType": 3,
                            },
                            {
                                "id": 10758,
                                "mainName": "Chapter 1 -1",
                                "subName": "The Two Alchemists",
                                "price": None,
                                "consumptionType": 3,
                            },
                        ]
                    }
                }
            }
        },
        SOURCE_URL,
    )
    assert result is not None
    return result


class FakePage:
    url = SOURCE_URL

    @staticmethod
    def title() -> str:
        return "Fullmetal Alchemist | Manga UP!"


class MangaUpSourceTests(unittest.TestCase):
    def test_registry_recognizes_work_and_segment_urls(self):
        registry = build_default_registry()

        work = registry.resolve(SOURCE_URL)
        segment = registry.resolve(f"{SOURCE_URL}/10758")

        self.assertEqual(work.adapter.id, "manga-up")
        self.assertEqual(segment.adapter.id, "manga-up")

    def test_catalog_preserves_the_public_source_limit(self):
        publication = publication_from_catalog(
            catalog(),
            source_url=SOURCE_URL,
            title="Fullmetal Alchemist",
        )

        self.assertEqual(publication.coverage.status, CoverageStatus.SOURCE_LIMITED)
        self.assertEqual(publication.coverage.available, 3)
        self.assertEqual(publication.coverage.expected, 4)
        self.assertEqual(publication.coverage.missing, 1)
        self.assertEqual([part.kind for part in publication.parts], [PartKind.SEGMENT] * 3)
        self.assertEqual(
            [part.number for part in publication.parts],
            ["1 -1", "1 -2", "1 -3"],
        )

    def test_normalized_catalog_drives_core_chapter_tasks(self):
        publication = publication_from_catalog(
            catalog(),
            source_url=SOURCE_URL,
            title="Fullmetal Alchemist",
        )

        tasks = _chapter_tasks_from_publication(publication)

        self.assertEqual([task.index for task in tasks], [1, 2, 3])
        self.assertEqual([task.number for task in tasks], ["1 -1", "1 -2", "1 -3"])
        self.assertTrue(all(task.pages is None for task in tasks))

    @patch("document_extractor.sources.manga_up.discover_manga_up_catalog")
    def test_adapter_uses_the_existing_catalog_detector(self, discover_catalog_mock):
        discover_catalog_mock.return_value = catalog()
        source = MangaUpSource()
        reference = SourceReference("manga-up", SOURCE_URL, SOURCE_URL)
        session = SourceSession(page=FakePage())

        publication = source.get_publication(reference, session)

        self.assertEqual(publication.title, "Fullmetal Alchemist")
        self.assertEqual(len(source.get_parts(publication, session)), 3)
        discover_catalog_mock.assert_called_once_with(session.page, SOURCE_URL)

    def test_adapter_exposes_update_capability(self):
        source = MangaUpSource()
        publication = publication_from_catalog(
            catalog(),
            source_url=SOURCE_URL,
            title="Fullmetal Alchemist",
        )

        result = source.check_updates(
            publication,
            publication.parts[:2],
            SourceSession(page=FakePage()),
        )

        self.assertIsInstance(source, UpdateCapability)
        self.assertEqual([part.number for part in result.parts], ["1 -3"])


if __name__ == "__main__":
    unittest.main()
