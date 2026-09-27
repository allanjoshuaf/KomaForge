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
        self.assertEqual(generic["status"], "experimental")
        self.assertEqual(generic["domains"], ["*"])
        self.assertTrue(generic["capabilities"]["update"])
        self.assertTrue(generic["capabilities"]["resources"])

        self.assertEqual(sources[0]["status"], "validated")
        self.assertEqual(sources[1]["languages"], ["en"])
        self.assertEqual(sources[2]["status"], "degraded")

    def test_families_are_reported_separately_from_sources(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["families", "--json"])
        families = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(
            [family["id"] for family in families],
            [
                "paginated-images",
                "vertical-images",
                "direct-document",
                "selectable-parts",
            ],
        )
        self.assertEqual(families[-1]["status"], "experimental")

    def test_sources_and_families_can_be_filtered_by_status(self):
        source_output = StringIO()
        family_output = StringIO()

        with redirect_stdout(source_output):
            source_code = main(["list", "--status", "validated", "--json"])
        with redirect_stdout(family_output):
            family_code = main(
                ["families", "--status", "experimental", "--json"]
            )

        sources = json.loads(source_output.getvalue())
        families = json.loads(family_output.getvalue())
        self.assertEqual(source_code, 0)
        self.assertEqual(family_code, 0)
        self.assertEqual([source["id"] for source in sources], ["calameo", "manga-up"])
        self.assertEqual(
            [family["id"] for family in families],
            ["selectable-parts"],
        )

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
        self.assertEqual(match["status"], "validated")
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
