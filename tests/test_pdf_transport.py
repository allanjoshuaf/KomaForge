from __future__ import annotations

import unittest
from unittest.mock import patch

from document_extractor.engine import (
    _fetch_browser_pdf as legacy_fetch_browser_pdf,
)
from document_extractor.engine import (
    _fetch_pdf_in_ranges as legacy_fetch_pdf_in_ranges,
)
from document_extractor.pdf_transport import fetch_browser_pdf, fetch_pdf_in_ranges


class PdfTransportTests(unittest.TestCase):
    def test_engine_keeps_historical_transport_imports(self):
        self.assertIs(legacy_fetch_browser_pdf, fetch_browser_pdf)
        self.assertIs(legacy_fetch_pdf_in_ranges, fetch_pdf_in_ranges)

    def test_large_pdf_is_reassembled_from_verified_byte_ranges(self):
        payload = b"%PDF-test-payload"

        class FakeResponse:
            status = 206

            def __init__(self, body):
                self._body = body

            def body(self):
                return self._body

        class FakeRequestContext:
            def __init__(self):
                self.ranges = []

            def fetch(self, _url, *, method, headers, timeout):
                self.assertions = (method, timeout)
                value = headers["range"].removeprefix("bytes=")
                start, end = (int(item) for item in value.split("-", 1))
                self.ranges.append((start, end))
                return FakeResponse(payload[start : end + 1])

        class FakeContext:
            def __init__(self):
                self.request = FakeRequestContext()

        class FakeRequest:
            url = "https://example.test/book.pdf"

        context = FakeContext()
        with patch("document_extractor.pdf_transport.PDF_RANGE_CHUNK_BYTES", 4):
            recovered = fetch_pdf_in_ranges(
                context, FakeRequest(), {"cookie": "session=test"}, len(payload)
            )

        self.assertEqual(recovered, payload)
        self.assertEqual(
            context.request.ranges,
            [(0, 3), (4, 7), (8, 11), (12, 15), (16, 16)],
        )
        self.assertEqual(context.request.assertions, ("GET", 60_000))

    def test_truncated_range_is_retried_then_rejected(self):
        class FakeResponse:
            status = 206

            def body(self):
                return b"x"

        class FakeRequestContext:
            calls = 0

            def fetch(self, *_args, **_kwargs):
                self.calls += 1
                return FakeResponse()

        context = type("Context", (), {"request": FakeRequestContext()})()
        request = type("Request", (), {"url": "https://example.test/book.pdf"})()

        with patch("document_extractor.pdf_transport.PDF_RANGE_CHUNK_BYTES", 4):
            with self.assertRaisesRegex(RuntimeError, "après deux tentatives"):
                fetch_pdf_in_ranges(context, request, {}, 4)

        self.assertEqual(context.request.calls, 2)

    def test_small_observed_pdf_is_reused_and_structurally_validated(self):
        payload = b"%PDF-observed"

        class FakeObservedResponse:
            ok = True
            status = 200
            headers = {"content-type": "application/pdf"}

            def body(self):
                return payload

        class FakeRequest:
            url = "https://example.test/book.pdf"

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
            "content_type": "application/octet-stream",
        }
        diagnostics = {
            "visible_page_count": 12,
            "detached_ordered_page_trees": [],
        }

        with patch(
            "document_extractor.pdf_transport.inspect_detached_page_trees",
            return_value=diagnostics,
        ) as inspect_pdf:
            data, page_count, result = fetch_browser_pdf(context, candidate)

        self.assertEqual(data, payload)
        self.assertEqual(page_count, 12)
        self.assertIs(result, diagnostics)
        inspect_pdf.assert_called_once_with(payload)


if __name__ == "__main__":
    unittest.main()
