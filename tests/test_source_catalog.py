from __future__ import annotations

import unittest

from document_extractor.sources import (
    BUILTIN_READER_FAMILIES,
    BUILTIN_SOURCE_CANDIDATES,
    GenericWebSource,
    SourceAccess,
    SourceIntegration,
    SourceMetadata,
    SourceStatus,
    build_default_registry,
    metadata_for,
)


class SourceCatalogTests(unittest.TestCase):
    def test_metadata_rejects_empty_domains(self):
        with self.assertRaisesRegex(ValueError, "source domain"):
            SourceMetadata(
                languages=("fr",),
                domains=(),
                version="1",
                status=SourceStatus.VALIDATED,
                status_reason="tested",
            )

    def test_undeclared_external_adapter_is_experimental(self):
        class ExternalAdapter:
            pass

        metadata = metadata_for(ExternalAdapter())

        self.assertEqual(metadata.status, SourceStatus.EXPERIMENTAL)
        self.assertEqual(metadata.integration, SourceIntegration.GENERIC)
        self.assertEqual(metadata.access, SourceAccess.VARIABLE)
        self.assertEqual(metadata.version, "unversioned")

    def test_generic_candidates_can_be_validated_without_becoming_specialized(self):
        candidates = {candidate.id: candidate for candidate in BUILTIN_SOURCE_CANDIDATES}

        for source_id in ("sushiscan", "mangareader-pro"):
            with self.subTest(source=source_id):
                candidate = candidates[source_id]
                self.assertEqual(candidate.status, SourceStatus.VALIDATED)
                self.assertEqual(candidate.integration, SourceIntegration.GENERIC)
                self.assertEqual(candidate.access, SourceAccess.FULL)

    def test_builtin_family_ids_are_unique(self):
        identifiers = [family.id for family in BUILTIN_READER_FAMILIES]

        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_builtin_sources_declare_only_known_families(self):
        family_ids = {family.id for family in BUILTIN_READER_FAMILIES}
        adapters = (*build_default_registry().all(), GenericWebSource())

        for adapter in adapters:
            metadata = metadata_for(adapter)
            with self.subTest(source=adapter.id):
                self.assertNotEqual(metadata.version, "unversioned")
                self.assertTrue(set(metadata.family_ids) <= family_ids)

        for candidate in BUILTIN_SOURCE_CANDIDATES:
            with self.subTest(candidate=candidate.id):
                self.assertTrue(set(candidate.family_ids) <= family_ids)
                self.assertEqual(candidate.adapter_id, "generic-web")

    def test_verification_dates_use_iso_format(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            SourceMetadata(
                languages=("fr",),
                domains=("example.test",),
                version="1",
                status=SourceStatus.EXPERIMENTAL,
                status_reason="test",
                last_verified="27/09/2026",
            )


if __name__ == "__main__":
    unittest.main()
