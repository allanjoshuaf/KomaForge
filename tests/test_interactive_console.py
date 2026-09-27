from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from document_extractor.interactive_console import (
    PLATFORM_MESSAGES,
    interactive_hub,
)
from document_extractor.jobs import JobAction, JobQueue, JobStatus
from document_extractor.library import SCHEMA_VERSION, LibraryIndex
from document_extractor.terminal_ui import TerminalUI


class InteractiveConsoleTests(unittest.TestCase):
    def test_platform_menu_catalog_is_complete_in_every_language(self):
        required = set(PLATFORM_MESSAGES["fr"])
        for language in ("fr", "en", "ru", "zh"):
            self.assertEqual(set(PLATFORM_MESSAGES[language]), required)

    def test_hub_returns_the_selected_extraction_mode(self):
        for choice, expected in (("1", "guided"), ("2", "advanced")):
            ui = TerminalUI("fr", stream=StringIO())
            with patch("builtins.input", return_value=choice):
                self.assertEqual(interactive_hub(ui), expected)

    def test_sources_are_visible_before_returning_to_extraction(self):
        stream = StringIO()
        ui = TerminalUI("fr", stream=stream)
        answers = iter(("3", "1", "5", "1"))

        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            mode = interactive_hub(ui)

        rendered = stream.getvalue()
        self.assertEqual(mode, "guided")
        self.assertIn("Calameo · validated", rendered)
        self.assertIn("eBooks.com · degraded", rendered)
        self.assertIn("Generic Web · experimental", rendered)
        self.assertLessEqual(max(map(len, rendered.splitlines())), 76)

    def test_library_can_be_rebuilt_and_inspected_from_the_hub(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(("4", "2", "1", "10", "1"))

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root)

            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            rendered = stream.getvalue()
            self.assertEqual(mode, "guided")
            self.assertEqual(index.schema_version(), SCHEMA_VERSION)
            self.assertIn("[OK] Reconstruire l’index", rendered)
            self.assertIn("Œuvres: 0", rendered)
            self.assertIn("Suivies: 0", rendered)

    def test_job_can_be_added_and_listed_from_the_hub(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue_path = root / "jobs.sqlite"
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(
                (
                    "5",
                    "2",
                    "https://example.test/book/1",
                    "1",
                    "9",
                    "1",
                )
            )

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root, queue_path=queue_path)

            jobs = JobQueue(queue_path).list()
            rendered = stream.getvalue()
            self.assertEqual(mode, "guided")
            self.assertEqual(len(jobs), 1)
            self.assertIs(jobs[0].action, JobAction.INSPECT)
            self.assertIs(jobs[0].status, JobStatus.PENDING)
            self.assertIn(jobs[0].id, rendered)
            self.assertIn("inspect · pending", rendered)


if __name__ == "__main__":
    unittest.main()
