from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from document_extractor.library import LibraryIndex
from document_extractor.library_service import LibraryService
from document_extractor.library_cli import main
from document_extractor.library_state import LibraryState
from document_extractor.jobs import JobAction, JobQueue


def write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/one",
                "publication": {
                    "type": "document",
                    "title": "One",
                    "part_count": 1,
                    "selected_part_count": 1,
                    "status": "complete",
                    "chapters": [
                        {
                            "index": 1,
                            "number": "1",
                            "title": "One",
                            "kind": "document",
                            "source_url": "https://example.test/one",
                            "status": "complete",
                            "detected": 1,
                            "expected": 1,
                            "pages": [
                                {
                                    "page": 1,
                                    "url": "https://cdn.example.test/one.webp",
                                    "file": "page-0001.webp",
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


class LibraryCliTests(unittest.TestCase):
    def test_read_json_keeps_reader_output_on_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            artifact = root / "One" / "one.cbz"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"archive")
            standard_output = StringIO()
            standard_error = StringIO()

            def read_artifact(_service, publication_id):
                self.assertEqual(publication_id, "publication-one")
                print("reader details")
                return artifact

            with patch.object(LibraryService, "read_artifact", read_artifact):
                with redirect_stdout(standard_output), redirect_stderr(standard_error):
                    code = main(
                        [
                            "read",
                            "publication-one",
                            "--root",
                            str(root),
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(standard_output.getvalue())["path"], str(artifact))
            self.assertIn("reader details", standard_error.getvalue())

    def test_continue_json_identifies_the_reopened_part(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            artifact = root / "Series" / "chapter-2.cbz"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"archive")
            reading = SimpleNamespace(
                publication=SimpleNamespace(id="publication-series", title="Series"),
                part=SimpleNamespace(id="part-two", title="Chapter 2"),
                path=artifact,
            )
            standard_output = StringIO()
            standard_error = StringIO()

            def continue_reading(_service):
                print("reader details")
                return reading

            with patch.object(LibraryService, "continue_reading", continue_reading):
                with redirect_stdout(standard_output), redirect_stderr(standard_error):
                    code = main(["continue", "--root", str(root), "--json"])

            payload = json.loads(standard_output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["part_id"], "part-two")
            self.assertEqual(payload["path"], str(artifact))
            self.assertIn("reader details", standard_error.getvalue())

    def test_rebuild_and_list_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            write_manifest(root / "One" / "pages.json")
            rebuilt = StringIO()
            with redirect_stdout(rebuilt):
                rebuild_code = main(
                    [
                        "rebuild",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--json",
                    ]
                )
            rebuild_payload = json.loads(rebuilt.getvalue())

            listed = StringIO()
            with redirect_stdout(listed):
                list_code = main(
                    ["list", "--root", str(root), "--index", str(index), "--json"]
                )
            list_payload = json.loads(listed.getvalue())

            self.assertEqual(rebuild_code, 0)
            self.assertEqual(rebuild_payload["works"], 1)
            self.assertEqual(list_code, 0)
            self.assertEqual(list_payload[0]["title"], "One")

    def test_list_creates_a_missing_index_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            output = StringIO()

            with redirect_stdout(output):
                code = main(["list", "--root", str(root)])

            self.assertEqual(code, 0)
            self.assertIn("Aucune œuvre indexée", output.getvalue())
            self.assertEqual(
                LibraryIndex(root / ".komaforge" / "library.sqlite").schema_version(),
                1,
            )

    def test_search_returns_only_matching_local_works(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            write_manifest(root / "One" / "pages.json")
            with redirect_stdout(StringIO()):
                main(["rebuild", "--root", str(root), "--index", str(index)])
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "search",
                        "one",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--json",
                    ]
                )

            results = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual([item["title"] for item in results], ["One"])

    def test_publications_exposes_the_identifier_required_by_track(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            write_manifest(root / "One" / "pages.json")
            with redirect_stdout(StringIO()):
                main(["rebuild", "--root", str(root), "--index", str(index)])
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "publications",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--json",
                    ]
                )
            publications = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(publications[0]["id"].startswith("publication-"))
            self.assertEqual(publications[0]["title"], "One")

    def test_status_summarizes_index_health(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            state = Path(temp) / "state.sqlite"
            queue = Path(temp) / "jobs.sqlite"
            write_manifest(root / "One" / "pages.json")
            with redirect_stdout(StringIO()):
                main(["rebuild", "--root", str(root), "--index", str(index)])
            publication_id = LibraryIndex(index).list_publications()[0]["id"]
            library_state = LibraryState(state)
            library_state.track(publication_id)
            library_state.assign_category(publication_id, "À lire")
            JobQueue(queue).enqueue(JobAction.INSPECT, "https://example.test/one")
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "status",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--state",
                        str(state),
                        "--queue",
                        str(queue),
                        "--json",
                    ]
                )
            status = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(status["works"], 1)
            self.assertEqual(status["coverage"], {"complete": 1})
            self.assertEqual(status["tracked"], 1)
            self.assertEqual(status["categories"], 1)
            self.assertEqual(status["unread"], 1)
            self.assertEqual(status["jobs"]["pending"], 1)

    def test_category_commands_group_tracked_publications(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            state = Path(temp) / "state.sqlite"
            write_manifest(root / "One" / "pages.json")
            with redirect_stdout(StringIO()):
                main(["rebuild", "--root", str(root), "--index", str(index)])
            publication_id = LibraryIndex(index).list_publications()[0]["id"]
            common = ["--root", str(root), "--index", str(index), "--state", str(state)]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["track", publication_id, *common]), 0)
                self.assertEqual(
                    main(["category-add", "À lire", publication_id, *common]), 0
                )

            members_output = StringIO()
            with redirect_stdout(members_output):
                code = main(["category-members", "à LIRE", *common, "--json"])
            members = json.loads(members_output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(members, [{"publication_id": publication_id, "title": "One"}])

    def test_track_progress_and_tracked_views(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = Path(temp) / "library.sqlite"
            state = Path(temp) / "state.sqlite"
            write_manifest(root / "One" / "pages.json")
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "rebuild",
                            "--root",
                            str(root),
                            "--index",
                            str(index),
                        ]
                    ),
                    0,
                )
            from document_extractor.library import LibraryIndex

            publication = next(LibraryIndex(index).iter_publications())
            normalized = LibraryIndex(index).load_publication(publication["id"])
            part_id = normalized.parts[0].id

            with redirect_stdout(StringIO()):
                track_code = main(
                    [
                        "track",
                        publication["id"],
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--state",
                        str(state),
                    ]
                )
                progress_code = main(
                    [
                        "progress",
                        publication["id"],
                        part_id,
                        "1",
                        "--complete",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--state",
                        str(state),
                    ]
                )
            output = StringIO()
            with redirect_stdout(output):
                tracked_code = main(
                    [
                        "tracked",
                        "--root",
                        str(root),
                        "--index",
                        str(index),
                        "--state",
                        str(state),
                        "--json",
                    ]
                )
            tracked = json.loads(output.getvalue())

            self.assertEqual(track_code, 0)
            self.assertEqual(progress_code, 0)
            self.assertEqual(tracked_code, 0)
            self.assertEqual(tracked[0]["title"], "One")
            self.assertEqual(tracked[0]["unread_parts"], 0)


if __name__ == "__main__":
    unittest.main()
