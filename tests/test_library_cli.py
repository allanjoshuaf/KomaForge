from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from document_extractor.library_cli import main


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

    def test_list_requires_a_current_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            error = StringIO()

            with redirect_stderr(error):
                code = main(["list", "--root", str(root)])

            self.assertEqual(code, 2)
            self.assertIn("rebuild", error.getvalue())

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
