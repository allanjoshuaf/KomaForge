from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from document_extractor.interactive_console import (
    PLATFORM_MESSAGES,
    interactive_hub,
)
from document_extractor.jobs import JobAction, JobQueue, JobStatus
from document_extractor.library import SCHEMA_VERSION, LibraryIndex
from document_extractor.library_service import LibraryService
from document_extractor.library_state import LibraryState
from document_extractor.terminal_ui import TerminalUI
from tests.test_library import write_manifest


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
        answers = iter(("3", "1", "8", "1"))

        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            mode = interactive_hub(ui)

        rendered = stream.getvalue()
        self.assertEqual(mode, "guided")
        self.assertIn("Calameo · validated", rendered)
        self.assertIn("eBooks.com · degraded", rendered)
        self.assertIn("Generic Web · experimental", rendered)
        self.assertLessEqual(max(map(len, rendered.splitlines())), 76)

    def test_remote_catalog_result_can_be_added_to_the_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            payload = {
                "results": [
                    {
                        "source_id": "mangadex",
                        "title": "Alchemy",
                        "authors": ["Author"],
                        "publication_url": "https://mangadex.org/title/12345678-1234-1234-1234-123456789abc",
                    }
                ],
                "errors": {},
            }
            added = SimpleNamespace(
                publication=SimpleNamespace(title="Alchemy")
            )
            answers = iter(("3", "5", "alchemy", "1", "original", "1", "8", "1"))

            with patch(
                "document_extractor.interactive_console.catalog_query",
                return_value=payload,
            ), patch.object(
                LibraryService,
                "add_url",
                return_value=added,
            ) as add_url, patch(
                "builtins.input",
                side_effect=lambda _prompt: next(answers),
            ):
                mode = interactive_hub(ui, root=root)

            self.assertEqual(mode, "guided")
            add_url.assert_called_once_with(
                payload["results"][0]["publication_url"],
                root.resolve(),
                options={
                    "chapters": "1",
                    "language": "fr",
                    "output_format": "original",
                    "scope": "auto",
                },
            )
            self.assertIn("[OK] Ajouté à la bibliothèque : Alchemy", stream.getvalue())

    def test_library_can_be_rebuilt_and_inspected_from_the_hub(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(("4", "15", "1", "23", "1"))

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root)

            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            rendered = stream.getvalue()
            self.assertEqual(mode, "guided")
            self.assertEqual(index.schema_version(), SCHEMA_VERSION)
            self.assertIn("[OK] Reconstruire l’index", rendered)
            self.assertIn("Œuvres: 0", rendered)
            self.assertIn("Suivies: 0", rendered)
            self.assertIn("Catégories: 0", rendered)
            self.assertIn("Reprendre la dernière lecture", rendered)
            self.assertIn("Lire dans KomaForge", rendered)

    def test_library_sync_is_available_from_the_hub(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(("4", "14", "23", "1"))

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root)

            self.assertEqual(mode, "guided")
            self.assertIn(
                "[OK] Synchroniser maintenant les publications suivies",
                stream.getvalue(),
            )

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
                    "10",
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

    def test_category_can_be_created_from_the_library_menu(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(("4", "15", "9", "3", "Favoris", "1", "7", "23", "1"))

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root)

            categories = LibraryState(root / ".komaforge" / "state.sqlite").categories()
            self.assertEqual(mode, "guided")
            self.assertEqual([category.name for category in categories], ["Favoris"])
            self.assertIn("[OK] Créer une catégorie : Favoris", stream.getvalue())

    def test_detected_updates_are_visible_and_can_be_acknowledged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            publication_id = index.list_publications()[0]["id"]
            state = LibraryState(root / ".komaforge" / "state.sqlite")
            state.track(publication_id)
            state.record_update(
                publication_id,
                "part-two",
                "Chapter 2",
                "https://example.test/one/chapter-2",
                download_job_id=JobQueue(
                    root / ".komaforge" / "jobs.sqlite"
                ).enqueue(
                    JobAction.DOWNLOAD,
                    "https://example.test/one/chapter-2",
                ).id,
            )
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(("4", "21", "22", "23", "1"))

            with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
                mode = interactive_hub(ui, root=root)

            self.assertEqual(mode, "guided")
            self.assertIn("Chapter 2", stream.getvalue())
            self.assertIn("pending", stream.getvalue())
            self.assertIn("nouveautés comme consultées : 1", stream.getvalue())
            self.assertEqual(state.updates(unseen_only=True), ())

    def test_library_reader_can_open_a_selected_part(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(
                root / "One" / "pages.json",
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            publication = index.load_publication(index.list_publications()[0]["id"])
            artifact = root / "One" / "one.cbz"
            stream = StringIO()
            ui = TerminalUI("fr", stream=stream)
            answers = iter(
                ("4", "11", publication.id, publication.parts[0].id, "23", "1")
            )

            with patch.object(
                LibraryService,
                "read_artifact",
                return_value=artifact,
            ) as read_artifact, patch(
                "builtins.input",
                side_effect=lambda _prompt: next(answers),
            ):
                mode = interactive_hub(ui, root=root)

            self.assertEqual(mode, "guided")
            read_artifact.assert_called_once_with(
                publication.id,
                part_id=publication.parts[0].id,
            )
            self.assertIn("one.cbz", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
