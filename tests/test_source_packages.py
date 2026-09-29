from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from document_extractor.source_packages import (
    build_runtime_registry,
    enabled_source_ids,
    inspect_source_package,
    inspect_source_packages,
    package_records,
    runtime_source_adapters,
    set_source_package_enabled,
)
from document_extractor.sources import SourceIntegration, UpdateCapability, metadata_for


def write_manifest(path: Path, **overrides) -> None:
    payload = {
        "schema_version": 1,
        "id": "example-reader",
        "name": "Example Reader",
        "version": "1.0.0",
        "languages": ["en"],
        "domains": ["reader.example.org"],
        "families": ["vertical-images"],
        "capabilities": ["url"],
        "permissions": {
            "network_domains": [
                "reader.example.org",
                "cdn.example.org",
            ],
            "browser": True,
            "filesystem": "none",
        },
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SourcePackageTests(unittest.TestCase):
    def test_valid_manifest_is_inspected_but_never_enabled_or_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "example.json"
            write_manifest(path)

            inspection = inspect_source_package(path)
            record = package_records(path.parent)[0]

            self.assertTrue(inspection.valid)
            self.assertEqual(inspection.manifest.id, "example-reader")
            self.assertEqual(
                inspection.manifest.network_domains,
                ("reader.example.org", "cdn.example.org"),
            )
            self.assertFalse(record["enabled"])
            self.assertFalse(record["executable"])

    def test_executable_entrypoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsafe.json"
            write_manifest(path, entrypoint="adapter.py:Source")

            inspection = inspect_source_package(path)

            self.assertFalse(inspection.valid)
            self.assertIn("unknown manifest fields: entrypoint", inspection.error)

    def test_builtin_source_id_and_filesystem_permission_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            builtin = Path(temp) / "builtin.json"
            filesystem = Path(temp) / "filesystem.json"
            write_manifest(builtin, id="calameo")
            write_manifest(
                filesystem,
                id="unsafe-files",
                permissions={
                    "network_domains": ["reader.example.org"],
                    "browser": False,
                    "filesystem": "library",
                },
            )

            self.assertIn(
                "conflicts with a built-in source",
                inspect_source_package(builtin).error,
            )
            self.assertIn(
                "cannot request filesystem access",
                inspect_source_package(filesystem).error,
            )

    def test_duplicate_ids_are_reported_without_hiding_first_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(root / "one.json")
            write_manifest(root / "two.json")

            inspections = inspect_source_packages(root)

            self.assertTrue(inspections[0].valid)
            self.assertFalse(inspections[1].valid)
            self.assertIn("duplicate source id", inspections[1].error)

    def test_explicit_activation_registers_a_code_free_generic_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(root / "example.json", capabilities=["url", "update"])

            enabled = set_source_package_enabled(
                root,
                "example-reader",
                enabled=True,
            )
            adapter = build_runtime_registry(root).get("example-reader")
            record = package_records(root)[0]

            self.assertEqual(enabled, ("example-reader",))
            self.assertEqual(enabled_source_ids(root), ("example-reader",))
            self.assertIsNotNone(adapter)
            self.assertEqual(adapter.network_domains, ("reader.example.org", "cdn.example.org"))
            self.assertIs(metadata_for(adapter).integration, SourceIntegration.GENERIC)
            self.assertIsInstance(adapter, UpdateCapability)
            self.assertTrue(record["enabled"])
            self.assertFalse(record["executable"])

            disabled = set_source_package_enabled(
                root,
                "example-reader",
                enabled=False,
            )

            self.assertEqual(disabled, ())
            self.assertIsNone(build_runtime_registry(root).get("example-reader"))

    def test_activation_rejects_unimplemented_capabilities_and_known_domains(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(
                root / "search.json",
                id="search-reader",
                capabilities=["url", "search"],
            )
            write_manifest(
                root / "known-domain.json",
                id="known-domain",
                domains=["sushiscan.net"],
                permissions={
                    "network_domains": ["sushiscan.net"],
                    "browser": True,
                    "filesystem": "none",
                },
            )

            with self.assertRaisesRegex(ValueError, "does not implement.*search"):
                set_source_package_enabled(root, "search-reader", enabled=True)
            with self.assertRaisesRegex(ValueError, "built-in source"):
                set_source_package_enabled(root, "known-domain", enabled=True)

    def test_candidate_ids_are_reserved_for_the_validated_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "candidate.json"
            write_manifest(path, id="sushiscan")

            inspection = inspect_source_package(path)

            self.assertFalse(inspection.valid)
            self.assertIn("conflicts with a built-in source", inspection.error)

    def test_runtime_fails_closed_when_enabled_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".enabled").write_text("missing-reader\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing or invalid"):
                runtime_source_adapters(root)


if __name__ == "__main__":
    unittest.main()
