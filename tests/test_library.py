from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from document_extractor.library import LibraryIndex, discover_manifests


def write_manifest(path: Path, source_url: str, title: str, page_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_url": source_url,
                "publication": {
                    "type": "document",
                    "title": title,
                    "part_count": 1,
                    "selected_part_count": 1,
                    "status": "complete",
                    "chapters": [
                        {
                            "index": 1,
                            "number": "1",
                            "title": title,
                            "kind": "document",
                            "source_url": source_url,
                            "status": "complete",
                            "detected": 1,
                            "expected": 1,
                            "expected_source": "test manifest",
                            "pages": [
                                {
                                    "page": 1,
                                    "url": page_url,
                                    "file": "page-0001.webp",
                                    "sha256": "a" * 64,
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


class LibraryIndexTests(unittest.TestCase):
    def test_ensure_builds_only_when_index_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.jpg",
            )
            index = LibraryIndex(database)

            summary, rebuilt = index.ensure(root)
            second_summary, rebuilt_again = index.ensure(root)

            self.assertTrue(rebuilt)
            self.assertEqual(summary.works, 1)
            self.assertFalse(rebuilt_again)
            self.assertIsNone(second_summary)

    def test_discovers_only_authoritative_manifest_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            write_manifest(
                root / "Two" / "publication.json",
                "https://example.test/two",
                "Two",
                "https://cdn.example.test/two.webp",
            )
            (root / "ignored.json").write_text("{}", encoding="utf-8")
            (root / ".komaforge-work").mkdir()
            write_manifest(
                root / ".komaforge-work" / "pages.json",
                "https://example.test/temporary",
                "Temporary",
                "https://cdn.example.test/temporary.webp",
            )

            manifests = discover_manifests(root)

            self.assertEqual(
                [path.name for path in manifests],
                ["pages.json", "publication.json"],
            )

    def test_rebuild_indexes_valid_manifests_and_can_be_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            write_manifest(
                root / "Two" / "pages.json",
                "https://example.test/two",
                "Two",
                "https://cdn.example.test/two.webp",
            )
            index = LibraryIndex(database)

            first = index.rebuild(root)
            second = index.rebuild(root)

            self.assertEqual(first, second)
            self.assertEqual(first.manifests, 2)
            self.assertEqual(first.duplicate_manifests, 0)
            self.assertEqual(first.works, 2)
            self.assertEqual(first.publications, 2)
            self.assertEqual(first.parts, 2)
            self.assertEqual(first.resources, 2)
            self.assertEqual(index.schema_version(), 1)
            self.assertEqual(
                [item["title"] for item in index.list_works()],
                ["One", "Two"],
            )
            self.assertEqual(
                [item["title"] for item in index.search_works("tw")],
                ["Two"],
            )
            status = index.status()
            self.assertEqual(status["works"], 2)
            self.assertEqual(status["publications"], 2)
            self.assertEqual(status["coverage"], {"complete": 2})
            publication_row = next(index.iter_publications())
            loaded = index.load_publication(publication_row["id"])
            self.assertEqual(loaded.id, publication_row["id"])
            self.assertEqual(loaded.title, publication_row["title"])

    def test_failed_rebuild_leaves_the_previous_index_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            manifest = root / "One" / "pages.json"
            write_manifest(
                manifest,
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            index = LibraryIndex(database)
            index.rebuild(root)
            manifest.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid KomaForge manifest"):
                index.rebuild(root)

            self.assertEqual(
                [item["title"] for item in index.list_works()],
                ["One"],
            )

    def test_sensitive_resource_locator_is_not_copied_into_sqlite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp?token=sensitive",
            )
            index = LibraryIndex(database)

            index.rebuild(root)

            self.assertEqual(index.resource_locators(), (None,))

    def test_session_scoped_publication_url_is_canonicalized_in_sqlite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            write_manifest(
                root / "One" / "pages.json",
                (
                    "https://reader.ebooks.com/preview?uid=temporary&reqid=1&"
                    "bid=347114076&t=2&hash=secret"
                ),
                "One",
                "https://cdn.example.test/one.webp",
            )
            index = LibraryIndex(database)

            index.rebuild(root)
            publication = index.list_publications()[0]

            self.assertEqual(
                publication["source_url"],
                "https://reader.ebooks.com/preview?bid=347114076",
            )
            self.assertNotIn("manifest_path", publication)
            self.assertTrue(
                all(
                    marker not in url
                    for url in index.source_urls()
                    for marker in ("uid=", "reqid=", "hash=", "t=")
                )
            )

    def test_search_treats_sql_wildcards_as_literal_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            write_manifest(
                root / "Percent" / "pages.json",
                "https://example.test/percent",
                "Book 100%",
                "https://cdn.example.test/percent.webp",
            )
            write_manifest(
                root / "Other" / "pages.json",
                "https://example.test/other",
                "Other",
                "https://cdn.example.test/other.webp",
            )
            index = LibraryIndex(database)
            index.rebuild(root)

            self.assertEqual(
                [item["title"] for item in index.search_works("100%")],
                ["Book 100%"],
            )

    def test_flat_historical_manifest_is_indexed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            manifest = root / "Historical-Book" / "pages.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "source_url": "https://example.test/historical",
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "expected": 1,
                        "detected": 1,
                        "saved": 1,
                        "missing": [],
                        "pages": [
                            {
                                "page": 1,
                                "url": "https://cdn.example.test/one.webp?_token_=secret",
                                "file": "page-0001.webp",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = LibraryIndex(database)

            summary = index.rebuild(root)

            self.assertEqual(summary.publications, 1)
            self.assertEqual(index.list_works()[0]["title"], "Historical-Book")
            self.assertEqual(index.resource_locators(), (None,))

    def test_duplicate_publication_prefers_status_then_integrity_then_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            source_url = "https://example.test/duplicate"
            inferior = root / "Inferior" / "pages.json"
            winner = root / "Winner" / "pages.json"
            write_manifest(
                inferior,
                source_url,
                "Duplicate",
                "https://cdn.example.test/inferior.webp",
            )
            write_manifest(
                winner,
                source_url,
                "Duplicate",
                "https://cdn.example.test/winner.webp",
            )
            inferior_payload = json.loads(inferior.read_text(encoding="utf-8"))
            inferior_payload["created_at"] = "2026-02-01T00:00:00+00:00"
            inferior_payload["publication"]["status"] = "incomplete"
            inferior_payload["publication"]["chapters"][0]["status"] = "incomplete"
            inferior.write_text(json.dumps(inferior_payload), encoding="utf-8")

            artifact = winner.parent / "document.cbz"
            artifact.write_bytes(b"verified archive")
            winner_payload = json.loads(winner.read_text(encoding="utf-8"))
            winner_payload["created_at"] = "2026-01-01T00:00:00+00:00"
            winner_payload["artifact"] = {
                "path": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
            winner.write_text(json.dumps(winner_payload), encoding="utf-8")
            index = LibraryIndex(database)

            summary = index.rebuild(root)
            publication = tuple(index.iter_publications())[0]

            self.assertEqual(summary.manifests, 2)
            self.assertEqual(summary.duplicate_manifests, 1)
            self.assertEqual(summary.publications, 1)
            self.assertEqual(Path(publication["manifest_path"]), winner.resolve())
            self.assertEqual(publication["artifact_integrity"], "verified")
            self.assertEqual(
                [item["title"] for item in index.list_downloaded()],
                ["Duplicate"],
            )
            self.assertEqual(index.artifact_paths(publication["id"]), (artifact.resolve(),))

    def test_artifact_paths_cannot_escape_the_publication_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            manifest = root / "One" / "pages.json"
            outside = root / "outside.cbz"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_bytes(b"archive")
            write_manifest(
                manifest,
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["artifact"] = {"path": "../outside.cbz"}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            index = LibraryIndex(database)
            index.rebuild(root)
            publication = index.list_publications()[0]

            with self.assertRaisesRegex(ValueError, "escapes"):
                index.artifact_paths(publication["id"])

    def test_duplicate_prefers_explicit_coverage_over_legacy_complete_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            source_url = "https://example.test/coverage"
            old = root / "Old" / "pages.json"
            current = root / "Current" / "pages.json"
            write_manifest(
                old,
                source_url,
                "Old claim",
                "https://cdn.example.test/old.webp",
            )
            old_payload = json.loads(old.read_text(encoding="utf-8"))
            old_payload["publication"]["chapters"][0].pop("expected")
            old.write_text(json.dumps(old_payload), encoding="utf-8")
            write_manifest(
                current,
                source_url,
                "Current evidence",
                "https://cdn.example.test/current.webp",
            )
            current_payload = json.loads(current.read_text(encoding="utf-8"))
            current_payload["publication"]["status"] = "incomplete"
            current_payload["publication"]["chapters"][0].update(
                {"status": "incomplete", "detected": 1, "expected": 2}
            )
            current.write_text(json.dumps(current_payload), encoding="utf-8")
            index = LibraryIndex(database)

            index.rebuild(root)
            publication = tuple(index.iter_publications())[0]

            self.assertEqual(publication["title"], "Current evidence")
            self.assertEqual(publication["coverage_status"], "incomplete")

    def test_catalog_scope_evidence_beats_an_old_single_part_complete_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            source_url = "https://global.manga-up.com/manga/126"
            old = root / "Old" / "pages.json"
            current = root / "Current" / "publication.json"
            write_manifest(
                old,
                source_url,
                "Old single chapter",
                "https://cdn.example.test/old.webp",
            )
            write_manifest(
                current,
                source_url,
                "Catalog-limited work",
                "https://cdn.example.test/current.webp",
            )
            current_payload = json.loads(current.read_text(encoding="utf-8"))
            current_payload["publication"].update(
                {
                    "status": "limited_by_source",
                    "availability": {
                        "catalog_part_count": 288,
                        "accessible_part_count": 1,
                        "access_limited": True,
                        "source": "source catalog",
                    },
                }
            )
            current.write_text(json.dumps(current_payload), encoding="utf-8")
            index = LibraryIndex(database)

            index.rebuild(root)
            publication = tuple(index.iter_publications())[0]

            self.assertEqual(publication["title"], "Catalog-limited work")
            self.assertEqual(publication["coverage_status"], "source_limited")
            self.assertEqual(publication["coverage_expected"], 288)

    def test_ebooks_reader_and_product_urls_share_one_library_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            database = Path(temp) / "library.sqlite"
            old = root / "Old" / "pages.json"
            current = root / "Current" / "pages.json"
            write_manifest(
                old,
                "https://reader.ebooks.com/preview?bid=347114076&token=old",
                "Old preview",
                "https://cdn.example.test/old.webp",
            )
            old_payload = json.loads(old.read_text(encoding="utf-8"))
            old_payload["publication"]["chapters"][0].pop("expected")
            old.write_text(json.dumps(old_payload), encoding="utf-8")
            write_manifest(
                current,
                "https://www.ebooks.com/en-us/book/347114076/the-demon-star/author/",
                "The Demon Star",
                "https://cdn.example.test/current.webp",
            )
            current_payload = json.loads(current.read_text(encoding="utf-8"))
            current_payload["publication"]["status"] = "incomplete"
            current_payload["publication"]["chapters"][0].update(
                {"status": "incomplete", "detected": 11, "expected": 62}
            )
            current.write_text(json.dumps(current_payload), encoding="utf-8")
            index = LibraryIndex(database)

            summary = index.rebuild(root)
            publications = index.list_publications()

            self.assertEqual(summary.duplicate_manifests, 1)
            self.assertEqual(len(publications), 1)
            self.assertEqual(publications[0]["title"], "The Demon Star")
            self.assertEqual(publications[0]["coverage_status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
