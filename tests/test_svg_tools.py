from __future__ import annotations

import unittest

from document_extractor.svg_tools import inspect_svg, remove_high_confidence_watermarks


SVG_WITH_SPECIMEN = b'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1200 1600">
<defs><style>.ff10{font-size:16px}</style></defs>
<image width="1200" height="1600" xlink:href="data:image/jpeg;base64,/9j/2Q=="/>
<text class="ff10 fs2 fc4 go2" transform="matrix(1.99 -1.99 1.99 1.99 148.06 1387.61)" textLength="522.30">SPECIMEN</text>
<text class="body" transform="matrix(1 0 0 1 10 50)">Texte normal</text>
</svg>'''


class SvgInspectionTests(unittest.TestCase):
    def test_inventory_matches_svg_structure(self):
        report = inspect_svg(SVG_WITH_SPECIMEN)
        self.assertEqual(report["tags"]["svg"], 1)
        self.assertEqual(report["tags"]["text"], 2)
        self.assertEqual(report["tags"]["image"], 1)
        self.assertEqual(report["embedded_images"], 1)
        self.assertEqual(report["text_count"], 2)

    def test_specimen_is_high_confidence_without_using_text_order(self):
        report = inspect_svg(SVG_WITH_SPECIMEN)
        self.assertTrue(report["high_confidence_watermark"])
        candidates = report["watermark_candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["text"], "SPECIMEN")
        self.assertGreaterEqual(candidates[0]["score"], 75)
        self.assertIn("transformation diagonale", candidates[0]["reasons"])

    def test_ordinary_text_is_not_a_watermark(self):
        report = inspect_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><text>Chapitre 1</text></svg>')
        self.assertFalse(report["high_confidence_watermark"])
        self.assertEqual(report["watermark_candidates"], [])

    def test_removal_is_targeted_and_does_not_depend_on_last_text(self):
        processed, removed = remove_high_confidence_watermarks(SVG_WITH_SPECIMEN)
        self.assertEqual([item["text"] for item in removed], ["SPECIMEN"])
        self.assertNotIn(b"SPECIMEN", processed)
        self.assertIn(b"Texte normal", processed)
        report = inspect_svg(processed)
        self.assertEqual(report["text_count"], 1)
        self.assertEqual(report["embedded_images"], 1)
        self.assertFalse(report["high_confidence_watermark"])


if __name__ == "__main__":
    unittest.main()
