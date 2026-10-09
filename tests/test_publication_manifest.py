from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from document_extractor.publication_manifest import (
    create_publication_manifest,
    flatten_single_document_manifest,
    select_stored_chapter_records,
    update_manifest_progress,
    write_json,
)


def make_manifest(*, source_limited: bool = False) -> dict:
    return create_publication_manifest(
        source_url="https://example.test/work",
        provider="Example",
        requested_output_format="original",
        watermark_policy="keep",
        watermark_texts=[],
        publication_type="work",
        output_title="Example Work",
        source_title="Example Work",
        source_metadata={"language": "fr"},
        part_kind="chapter",
        part_count=2,
        selected_part_count=2,
        catalog_part_count=12 if source_limited else None,
        accessible_part_count=2 if source_limited else None,
        source_limited=source_limited,
        availability_source="public catalog" if source_limited else None,
    )


class PublicationManifestTests(unittest.TestCase):
    def test_complete_work_requires_every_part(self):
        manifest = make_manifest()
        complete = update_manifest_progress(
            manifest,
            [
                {"index": 1, "status": "complete"},
                {"index": 2, "status": "complete"},
            ],
            completed=True,
            publication_is_work=True,
            all_part_count=2,
            source_limited=False,
        )

        self.assertTrue(complete)
        self.assertEqual(manifest["publication"]["status"], "complete")

    def test_missing_part_keeps_work_incomplete(self):
        manifest = make_manifest()
        complete = update_manifest_progress(
            manifest,
            [{"index": 1, "status": "complete"}],
            completed=True,
            publication_is_work=True,
            all_part_count=2,
            source_limited=False,
        )

        self.assertFalse(complete)
        self.assertEqual(manifest["publication"]["status"], "incomplete")

    def test_complete_accessible_subset_preserves_source_limit(self):
        manifest = make_manifest(source_limited=True)
        complete = update_manifest_progress(
            manifest,
            [
                {"index": 1, "status": "complete"},
                {"index": 2, "status": "complete"},
            ],
            completed=True,
            publication_is_work=True,
            all_part_count=2,
            source_limited=True,
        )

        self.assertTrue(complete)
        self.assertEqual(
            manifest["publication"]["status"],
            "limited_by_source",
        )
        self.assertEqual(
            manifest["publication"]["availability"][
                "selected_accessible_part_count"
            ],
            2,
        )

    def test_failed_refresh_does_not_replace_completed_part(self):
        stored = select_stored_chapter_records(
            [
                {
                    "index": 1,
                    "number": "1",
                    "source_url": "https://example.test/chapter/1",
                    "status": "complete",
                }
            ],
            [
                {
                    "index": 1,
                    "number": "1",
                    "source_url": "https://example.test/chapter/1",
                    "status": "error",
                }
            ],
            publication_is_work=True,
            inspect=False,
        )

        self.assertEqual(stored[0]["status"], "complete")

    def test_single_document_fields_are_flattened_and_serializable(self):
        manifest = make_manifest()
        manifest["publication"]["type"] = "document"
        record = {
            "index": 1,
            "number": "1",
            "title": "Document",
            "kind": "document",
            "source_url": "https://example.test/document",
            "detected": 4,
            "saved": 4,
            "status": "complete",
            "artifact": {"path": "document.pdf"},
        }
        flatten_single_document_manifest(manifest, record)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pages.json"
            write_json(path, manifest)
            serialized = path.read_text(encoding="utf-8")

        self.assertEqual(manifest["publication"]["chapters"][0]["page_count"], 4)
        self.assertEqual(manifest["saved"], 4)
        self.assertIn('"document.pdf"', serialized)


if __name__ == "__main__":
    unittest.main()
