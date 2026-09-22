from __future__ import annotations

import base64
import gzip
import unittest

from document_extractor.resources import (
    decode_data_uri,
    detect_resource,
    is_page_resource,
)


SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><text>Page</text></svg>'


class ResourceDetectionTests(unittest.TestCase):
    def test_plain_svg_named_svgz_is_detected_without_gzip(self):
        info = detect_resource(SVG, "application/octet-stream", "https://example.test/p2.svgz")
        self.assertEqual(info.kind, "svg")
        self.assertEqual(info.extension, ".svg")
        self.assertEqual(info.data, SVG)
        self.assertTrue(info.normalized)
        self.assertIn("non compressé", info.normalization)

    def test_real_svgz_is_decompressed_and_identified(self):
        compressed = gzip.compress(SVG)
        info = detect_resource(compressed, "image/svg+xml", "https://example.test/p2.svgz")
        self.assertEqual(info.kind, "svg")
        self.assertEqual(info.data, SVG)
        self.assertNotEqual(info.source_sha256, info.sha256)
        self.assertEqual(info.normalization, "gzip vers svg")

    def test_data_uri_is_decoded_then_detected(self):
        uri = "data:image/svg+xml;base64," + base64.b64encode(SVG).decode("ascii")
        data, media_type = decode_data_uri(uri)
        info = detect_resource(data, media_type, uri)
        self.assertEqual(info.kind, "svg")
        self.assertTrue(is_page_resource(info))

    def test_magic_bytes_win_over_wrong_content_type(self):
        png = b"\x89PNG\r\n\x1a\n" + b"placeholder"
        info = detect_resource(png, "text/html", "https://example.test/page.bin")
        self.assertEqual(info.extension, ".png")

    def test_unknown_resource_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inconnu"):
            detect_resource(b"not a known resource", "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
