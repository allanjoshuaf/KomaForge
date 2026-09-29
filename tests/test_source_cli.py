from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from document_extractor.source_cli import main
from tests.test_mangadex_source import FakeApi
from tests.test_source_packages import write_manifest


class SourceCliTests(unittest.TestCase):
    def test_extensions_command_inspects_manifests_without_loading_code(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            write_manifest(directory / "example.json")
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "extensions",
                        "--directory",
                        str(directory),
                        "--json",
                    ]
                )
            records = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(records[0]["id"], "example-reader")
            self.assertFalse(records[0]["enabled"])
            self.assertFalse(records[0]["executable"])

    @patch("document_extractor.sources.mangadex._fetch_json", new_callable=FakeApi)
    def test_search_queries_capable_sources_and_returns_stable_json(self, _api):
        output = StringIO()

        with redirect_stdout(output):
            code = main(
                [
                    "search",
                    "fullmetal",
                    "--source",
                    "mangadex",
                    "--language",
                    "en",
                    "--json",
                ]
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["errors"], {})
        self.assertEqual(payload["results"][0]["source_id"], "mangadex")
        self.assertEqual(payload["results"][0]["title"], "Fullmetal Alchemist")
        self.assertTrue(payload["results"][0]["publication_url"].startswith("https://"))

    def test_list_reports_specialized_and_generic_sources(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["list", "--json"])
        sources = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(
            [source["id"] for source in sources],
            ["calameo", "manga-up", "ebooks", "mangadex", "generic-web"],
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
        self.assertEqual(sources[0]["last_verified"], "2026-09-28")
        self.assertEqual(sources[1]["languages"], ["en"])
        self.assertEqual(sources[1]["access"], "source_limited")
        self.assertEqual(sources[2]["status"], "degraded")
        self.assertEqual(sources[2]["access"], "session_dependent")
        self.assertTrue(sources[3]["capabilities"]["search"])
        self.assertTrue(sources[3]["capabilities"]["browse"])

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
        vertical = next(
            family for family in families if family["id"] == "vertical-images"
        )
        self.assertEqual(
            vertical["strategies"],
            [
                "virtual-blob",
                "chapter-manifest",
                "document-images",
                "grouped-images",
            ],
        )
        selectable = next(
            family for family in families if family["id"] == "selectable-parts"
        )
        self.assertEqual(
            selectable["strategies"],
            ["linked-chapters", "select-control"],
        )

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

    def test_status_summarizes_sources_candidates_and_families(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(["status", "--json"])
        status = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(status["sources"]["total"], 5)
        self.assertEqual(status["sources"]["by_status"]["validated"], 2)
        self.assertEqual(status["sources"]["by_status"]["degraded"], 1)
        self.assertEqual(status["sources"]["by_status"]["experimental"], 2)
        self.assertEqual(status["sources"]["search"], ["mangadex"])
        self.assertEqual(status["sources"]["browse"], ["mangadex"])
        self.assertEqual(status["candidates"]["by_status"]["validated"], 2)
        self.assertEqual(status["families"]["total"], 4)
        self.assertEqual(status["families"]["strategies"], 8)

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
        self.assertFalse(match["candidate"])
        self.assertEqual(match["adapter_id"], "generic-web")

    def test_match_preserves_validated_generic_site_identity(self):
        output = StringIO()

        with redirect_stdout(output):
            code = main(
                [
                    "match",
                    "https://sushiscan.net/vagabond-volume-1/",
                    "--json",
                ]
            )
        match = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(match["id"], "sushiscan")
        self.assertEqual(match["name"], "SushiScan")
        self.assertEqual(match["status"], "validated")
        self.assertEqual(match["integration"], "generic")
        self.assertEqual(match["adapter_id"], "generic-web")
        self.assertTrue(match["candidate"])
        self.assertFalse(match["specialized"])
        self.assertEqual(match["confidence"], "high")
        self.assertIn("routed through generic-web", match["reason"])


if __name__ == "__main__":
    unittest.main()
