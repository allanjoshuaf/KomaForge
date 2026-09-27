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


if __name__ == "__main__":
    unittest.main()
