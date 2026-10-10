from __future__ import annotations

import unittest

from document_extractor.diagnostic_ui import localize_diagnostic


class DiagnosticTranslationTests(unittest.TestCase):
    def test_coverage_counts_and_missing_pages_survive_translation(self):
        message = "[INCOMPLET] Publication : 39/393 pages (354 manquante(s))"
        for language in ("en", "ru", "zh"):
            with self.subTest(language=language):
                result = localize_diagnostic(message, language)
                self.assertNotIn("manquante", result)
                self.assertIn("39/393", result)
                self.assertIn("354", result)

    def test_range_progress_keeps_exact_byte_counts(self):
        message = "Récupération PDF : segment 2/8 (8388608/32494334 octets)"
        for language in ("en", "ru", "zh"):
            result = localize_diagnostic(message, language)
            self.assertIn("8388608/32494334", result)
            self.assertNotIn("octets", result)

    def test_scribd_blank_page_warning_keeps_page_number_and_refusal(self):
        message = (
            "Scribd expose du texte DOM, mais la page rendue 23 reste visuellement vide. "
            "KomaForge refuse d'annoncer cette publication comme complète."
        )
        for language in ("en", "ru", "zh"):
            translated = localize_diagnostic(message, language)
            self.assertIn("23", translated)
            self.assertNotIn("visuellement", translated)

    def test_unknown_server_error_is_preserved(self):
        message = "HTTP 403: source-specific response"
        self.assertEqual(localize_diagnostic(message, "zh"), message)
