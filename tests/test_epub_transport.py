from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.engine import _fetch_browser_epub as legacy_fetch_browser_epub
from document_extractor.epub_transport import fetch_browser_epub


class EpubTransportTests(unittest.TestCase):
    def test_engine_keeps_historical_transport_import(self):
        self.assertIs(legacy_fetch_browser_epub, fetch_browser_epub)

    def test_small_observed_epub_is_reused_and_validated(self):
        payload = b"epub-observed"

        class FakeObservedResponse:
            ok = True
            status = 200

            def body(self):
                return payload

        class FakeRequest:
            url = "https://example.test/book.epub"

            def all_headers(self):
                return {"cookie": "session=test"}

        class FakeRequestContext:
            def fetch(self, *_args, **_kwargs):
                raise AssertionError("La réponse observée devait être réutilisée.")

        context = type("Context", (), {"request": FakeRequestContext()})()
        candidate = {
            "request": FakeRequest(),
            "response": FakeObservedResponse(),
            "content_length": len(payload),
        }
        info = {"spine_count": 8, "missing_documents": []}

        with patch(
            "document_extractor.epub_transport.inspect_epub",
            return_value=info,
        ) as inspect_document:
            data, result = fetch_browser_epub(context, candidate, "fr")

        self.assertEqual(data, payload)
        self.assertIs(result, info)
        inspect_document.assert_called_once_with(payload)

    def test_failed_replay_is_retried_then_rejected(self):
        class FakeRequest:
            url = "https://example.test/book.epub"

            def all_headers(self):
                return {"cookie": "session=test", "range": "bytes=0-10"}

        class FakeRequestContext:
            def __init__(self):
                self.calls = []

            def fetch(self, _url, *, method, headers, timeout):
                self.calls.append((method, headers, timeout))
                raise RuntimeError("indisponible")

        request_context = FakeRequestContext()
        context = type("Context", (), {"request": request_context})()
        candidate = {"request": FakeRequest(), "content_length": 0}

        with self.assertRaisesRegex(RuntimeError, "après deux tentatives"):
            fetch_browser_epub(context, candidate)

        self.assertEqual(len(request_context.calls), 2)
        self.assertEqual(request_context.calls[0][0], "GET")
        self.assertEqual(request_context.calls[0][2], 180_000)
        self.assertNotIn("range", request_context.calls[0][1])


if __name__ == "__main__":
    unittest.main()
