from __future__ import annotations

import unittest

from document_extractor.browser_session import (
    _http_origin_warmup_url,
    cleanup_temporary_profile,
    navigate_to_source,
)
from document_extractor.engine import (
    cleanup_temporary_profile as legacy_cleanup_temporary_profile,
)
from document_extractor.engine import navigate_to_source as legacy_navigate_to_source


class BrowserSessionTests(unittest.TestCase):
    def test_engine_keeps_historical_browser_session_imports(self):
        self.assertIs(legacy_cleanup_temporary_profile, cleanup_temporary_profile)
        self.assertIs(legacy_navigate_to_source, navigate_to_source)

    def test_ssl_warmup_uses_only_a_plain_origin(self):
        self.assertEqual(
            _http_origin_warmup_url("https://example.test/private/book?token=secret"),
            "http://example.test/",
        )

    def test_ssl_warmup_rejects_credentials_and_custom_ports(self):
        self.assertIsNone(_http_origin_warmup_url("https://user@example.test/book"))
        self.assertIsNone(_http_origin_warmup_url("https://example.test:8443/book"))
        self.assertIsNone(_http_origin_warmup_url("http://example.test/book"))


if __name__ == "__main__":
    unittest.main()
