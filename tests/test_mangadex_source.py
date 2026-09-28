from __future__ import annotations

import unittest

from document_extractor.models import CoverageStatus, ResourceKind
from document_extractor.sources import (
    BrowseCapability,
    MangaDexSource,
    SearchCapability,
    SourceReference,
    SourceSession,
    UpdateCapability,
    build_default_registry,
)


MANGA_ID = "f9c9614d-0657-44c6-9c33-47fd58cd51b3"
CHAPTER_ID = "c1cd24a8-d989-4abe-873b-bd6f69892a74"
TITLE_URL = f"https://mangadex.org/title/{MANGA_ID}"


def manga_item():
    return {
        "id": MANGA_ID,
        "attributes": {
            "title": {"en": "Fullmetal Alchemist"},
            "status": "completed",
            "tags": [
                {"attributes": {"name": {"en": "Action"}}},
            ],
        },
        "relationships": [
            {"type": "author", "attributes": {"name": "Hiromu Arakawa"}},
            {"type": "artist", "attributes": {"name": "Hiromu Arakawa"}},
            {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
        ],
    }


def chapter_item(number="1", chapter_id=CHAPTER_ID):
    return {
        "id": chapter_id,
        "attributes": {
            "chapter": number,
            "volume": "1",
            "title": "The Two Alchemists",
            "translatedLanguage": "en",
            "pages": 2,
            "externalUrl": None,
        },
        "relationships": [
            {
                "type": "scanlation_group",
                "attributes": {"name": "Example Group"},
            },
            {"type": "manga", "id": MANGA_ID},
        ],
    }


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, url, parameters=None):
        self.calls.append((url, dict(parameters or {})))
        if url.endswith(f"/manga/{MANGA_ID}"):
            return {"result": "ok", "data": manga_item()}
        if url.endswith(f"/manga/{MANGA_ID}/feed"):
            return {
                "result": "ok",
                "data": [
                    chapter_item(),
                    chapter_item("2", "37633d7f-6e1c-42ce-80e3-6492fd8e1e18"),
                ],
                "total": 2,
            }
        if url.endswith(f"/at-home/server/{CHAPTER_ID}"):
            return {
                "result": "ok",
                "baseUrl": "https://uploads.example.test",
                "chapter": {
                    "hash": "digest",
                    "data": ["page-1.jpg", "page-2.jpg"],
                },
            }
        if url.endswith("/manga"):
            return {"result": "ok", "data": [manga_item()], "total": 1}
        raise AssertionError(url)


class MangaDexSourceTests(unittest.TestCase):
    def test_registry_and_capabilities_are_explicit(self):
        source = build_default_registry().resolve(TITLE_URL).adapter

        self.assertEqual(source.id, "mangadex")
        self.assertIsInstance(source, SearchCapability)
        self.assertIsInstance(source, BrowseCapability)
        self.assertIsInstance(source, UpdateCapability)
        self.assertEqual(
            build_default_registry()
            .resolve(f"{TITLE_URL}/fullmetal-alchemist")
            .adapter.id,
            "mangadex",
        )

    def test_title_builds_attributed_parts_and_original_resources(self):
        api = FakeApi()
        source = MangaDexSource(api)
        publication = source.get_publication(
            SourceReference(source.id, TITLE_URL, TITLE_URL),
            SourceSession(options={"language": "en"}),
        )

        resources = source.get_resources(publication.parts[0], SourceSession())

        self.assertEqual(publication.title, "Fullmetal Alchemist")
        self.assertEqual(publication.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(len(publication.parts), 2)
        self.assertEqual(
            publication.parts[0].metadata["scanlation_groups"],
            ("Example Group",),
        )
        self.assertEqual(len(resources.resources), 2)
        self.assertTrue(
            resources.resources[0].locator.endswith("/data/digest/page-1.jpg")
        )
        self.assertEqual(resources.resources[0].kind, ResourceKind.IMAGE)
        self.assertEqual(resources.coverage.status, CoverageStatus.COMPLETE)

    def test_search_and_browse_return_normalized_works(self):
        api = FakeApi()
        source = MangaDexSource(api)
        session = SourceSession(options={"language": "en"})

        searched = source.search("fullmetal", {}, 1, session)
        popular = source.popular(1, session)
        latest = source.latest(1, session)

        self.assertEqual(searched.works[0].title, "Fullmetal Alchemist")
        self.assertEqual(searched.works[0].authors, ("Hiromu Arakawa",))
        self.assertEqual(searched.works[0].genres, ("Action",))
        self.assertIn("uploads.mangadex.org/covers", searched.works[0].cover_url)
        self.assertEqual(popular.works[0].publications[0].source_id, "mangadex")
        self.assertEqual(latest.page, 1)


if __name__ == "__main__":
    unittest.main()
