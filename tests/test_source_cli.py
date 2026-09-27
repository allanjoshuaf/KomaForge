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
        self.assertEqual(generic["compatibility"], "experimental")
        self.assertEqual(generic["integration"], "generic")
        self.assertEqual(generic["access"], "variable")
        self.assertEqual(generic["domains"], ["*"])
        self.assertTrue(generic["capabilities"]["update"])
        self.assertTrue(generic["capabilities"]["resources"])

        self.assertEqual(sources[0]["status"], "validated")
        self.assertEqual(sources[0]["last_verified"], "2026-09-27")
        self.assertEqual(sources[1]["languages"], ["en"])
        self.assertEqual(sources[1]["access"], "source_limited")
        self.assertEqual(sources[2]["status"], "degraded")
        self.assertEqual(sources[2]["access"], "session_dependent")

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

    def test_candidates_are_distinct_from_specialized_sources(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["candidates", "--status", "validated", "--json"])
        candidates = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(
            [candidate["id"] for candidate in candidates],
            ["sushiscan", "mangareader-pro"],
        )
        self.assertTrue(
            all(candidate["adapter_id"] == "generic-web" for candidate in candidates)
        )
        self.assertTrue(
            all(candidate["last_verified"] == "2026-09-28" for candidate in candidates)
        )
        self.assertTrue(
            all(candidate["integration"] == "generic" for candidate in candidates)
        )
        self.assertTrue(all(candidate["access"] == "full" for candidate in candidates))

    def test_sources_can_be_filtered_by_integration_and_access(self):
        source_output = StringIO()
        candidate_output = StringIO()

        with redirect_stdout(source_output):
            source_code = main(
                ["list", "--integration", "specialized", "--access", "source_limited", "--json"]
            )
        with redirect_stdout(candidate_output):
            candidate_code = main(
                ["candidates", "--integration", "generic", "--access", "full", "--json"]
            )

        self.assertEqual(source_code, 0)
        self.assertEqual(candidate_code, 0)
        self.assertEqual(
            [source["id"] for source in json.loads(source_output.getvalue())],
            ["manga-up"],
        )
        self.assertEqual(
            [candidate["id"] for candidate in json.loads(candidate_output.getvalue())],
            ["sushiscan", "mangareader-pro"],
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
