from __future__ import annotations

import unittest

from document_extractor.providers import _calameo_book_code, build_calameo_pages


class CalameoProviderTests(unittest.TestCase):
    def test_recognizes_only_calameo_read_urls(self):
        self.assertEqual(
            _calameo_book_code("https://www.calameo.com/read/abc_123"),
            "abc_123",
        )
        self.assertIsNone(_calameo_book_code("https://example.test/read/abc_123"))
        self.assertIsNone(_calameo_book_code("https://www.calameo.com/books/abc_123"))

    def test_builds_every_signed_svgz_page_from_verified_metadata(self):
        content = {
            "key": "book-key",
            "name": "Mon livre de test",
            "document": {"pages": 3},
            "domains": {
                "secured": {"svg": "https://ps.calameoassets.com/"}
            },
        }
        loaded = [
            "https://ps.calameoassets.com/book-key/p1.svgz?token=signed"
        ]

        result = build_calameo_pages(content, loaded)

        self.assertEqual(result.name, "calameo")
        self.assertEqual(result.publication_type, "book")
        self.assertEqual(result.title, "Mon livre de test")
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(result.chapters[0].title, "Mon livre de test")
        self.assertEqual(result.chapters[0].number, "1")
        self.assertEqual(result.chapters[0].expected.value, 3)
        self.assertEqual(result.allowed_hosts, {"ps.calameoassets.com"})
        self.assertEqual(
            [page["url"] for page in result.pages],
            [
                "https://ps.calameoassets.com/book-key/p1.svgz?token=signed",
                "https://ps.calameoassets.com/book-key/p2.svgz?token=signed",
                "https://ps.calameoassets.com/book-key/p3.svgz?token=signed",
            ],
        )

    def test_rejects_an_unverified_page_host(self):
        content = {
            "key": "book-key",
            "document": {"pages": 3},
            "domains": {
                "secured": {"svg": "https://ps.calameoassets.com/"}
            },
        }

        with self.assertRaisesRegex(RuntimeError, "signée et vérifiable"):
            build_calameo_pages(
                content,
                ["https://attacker.test/book-key/p1.svgz?token=signed"],
            )


if __name__ == "__main__":
    unittest.main()
