from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from document_extractor.source_cli import main


class SourceCliTests(unittest.TestCase):
    def test_list_reports_specialized_and_generic_sources(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["list", "--json"])
        sources = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(
            [source["id"] for source in sources],
            ["calameo", "manga-up", "ebooks", "generic-web"],
        )
        generic = sources[-1]
        self.assertFalse(generic["specialized"])
        self.assertTrue(generic["capabilities"]["update"])

    def test_match_explains_specialized_routing(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(
                [
                    "match",
                    "https://global.manga-up.com/manga/126",
                    "--json",
                ]
            )
        match = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(match["id"], "manga-up")
        self.assertTrue(match["specialized"])
        self.assertEqual(match["confidence"], "high")
        self.assertTrue(match["capabilities"]["update"])

    def test_match_makes_generic_fallback_explicit(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["match", "https://example.test/book", "--json"])
        match = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(match["id"], "generic-web")
        self.assertFalse(match["specialized"])


if __name__ == "__main__":
    unittest.main()
