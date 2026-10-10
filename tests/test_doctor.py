from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from document_extractor.cli import main
from document_extractor.doctor import run_doctor
from tests.test_source_packages import write_manifest


class DoctorTests(unittest.TestCase):
    def test_fresh_installation_is_healthy_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "future-library"
            sources = Path(temp) / "sources"

            report = run_doctor(
                root=root,
                chrome=Path(sys.executable),
                sources_directory=sources,
            )

            self.assertEqual(report.status, "pass")
            self.assertFalse(root.exists())
            checks = {check.id: check for check in report.checks}
            self.assertIn("reconstructible", checks["library-index"].summary)
            self.assertIn("can be created", checks["output-root"].summary)

    def test_incompatible_library_schema_is_a_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app_dir = root / ".komaforge"
            app_dir.mkdir()
            with closing(sqlite3.connect(app_dir / "library.sqlite")) as connection:
                connection.execute(
                    "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', '99')"
                )
                connection.commit()

            report = run_doctor(
                root=root,
                chrome=Path(sys.executable),
                sources_directory=root / "sources",
            )

            self.assertEqual(report.status, "fail")
            check = next(item for item in report.checks if item.id == "library-index")
            self.assertIn("incompatible schema version 99", check.summary)

    def test_rejected_extension_is_a_warning_not_executable_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / "sources"
            sources.mkdir()
            write_manifest(sources / "unsafe.json", entrypoint="adapter.py:Source")

            report = run_doctor(
                root=root,
                chrome=Path(sys.executable),
                sources_directory=sources,
            )

            self.assertEqual(report.status, "warn")
            check = next(item for item in report.checks if item.id == "source-packages")
            self.assertIn("1 rejected", check.summary)

    def test_older_supported_state_schema_is_reported_as_migratable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app_dir = root / ".komaforge"
            app_dir.mkdir()
            with closing(sqlite3.connect(app_dir / "state.sqlite")) as connection:
                connection.execute(
                    "CREATE TABLE state_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO state_metadata(key, value) VALUES('schema_version', '2')"
                )
                connection.commit()

            report = run_doctor(
                root=root,
                chrome=Path(sys.executable),
                sources_directory=root / "sources",
            )

            self.assertEqual(report.status, "warn")
            check = next(item for item in report.checks if item.id == "library-state")
            self.assertIn("will migrate to 3", check.summary)

    def test_main_command_dispatches_stable_json_report(self):
        with tempfile.TemporaryDirectory() as temp:
            output = StringIO()
            root = Path(temp) / "library"
            with redirect_stdout(output):
                code = main(
                    [
                        "doctor",
                        "--root",
                        str(root),
                        "--chrome",
                        sys.executable,
                        "--sources-directory",
                        str(Path(temp) / "sources"),
                        "--json",
                    ]
                )
            payload = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "pass")
            self.assertGreaterEqual(payload["counts"]["pass"], 9)
            self.assertEqual(payload["counts"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
