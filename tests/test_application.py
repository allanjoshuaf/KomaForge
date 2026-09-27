from __future__ import annotations

import unittest

from document_extractor.application import resolve_source


class SourceRoutingTests(unittest.TestCase):
    def test_known_source_is_selected_once_as_specialized(self):
        route = resolve_source("https://www.calameo.com/read/abc_123")

        self.assertTrue(route.specialized)
        self.assertEqual(route.adapter.id, "calameo")

    def test_unknown_http_site_uses_the_explicit_generic_fallback(self):
        route = resolve_source("https://example.test/publication")

        self.assertFalse(route.specialized)
        self.assertEqual(route.adapter.id, "generic-web")

    def test_non_web_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no KomaForge source"):
            resolve_source("file:///tmp/book.pdf")


if __name__ == "__main__":
    unittest.main()
