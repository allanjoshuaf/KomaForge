from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from document_extractor.library import LibraryIndex
from document_extractor.library_service import LibraryService
from document_extractor.library_state import LibraryState

from tests.test_library import write_manifest


class LibraryStateTests(unittest.TestCase):
    def _service(self, temp: str):
        root = Path(temp) / "outputs"
        manifest = root / "One" / "pages.json"
        write_manifest(
            manifest,
            "https://example.test/one",
            "One",
            "https://cdn.example.test/one.webp",
        )
        index = LibraryIndex(Path(temp) / "library.sqlite")
        index.rebuild(root)
        state = LibraryState(Path(temp) / "state.sqlite")
        return root, index, state, LibraryService(index, state)

    def test_tracking_and_progress_survive_index_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            root, index, state, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            part = publication.parts[0]

            tracked = service.track(publication.id)
            progress = service.record_progress(
                publication.id,
                part.id,
                1,
                completed=True,
            )
            index.rebuild(root)
            views = service.tracked()

            self.assertEqual(tracked.publication_id, publication.id)
            self.assertTrue(progress.completed)
            self.assertEqual(len(state.progress()), 1)
            self.assertEqual(views[0].completed_parts, 1)
            self.assertEqual(views[0].unread_parts, 0)

    def test_unknown_publication_cannot_be_tracked(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, service = self._service(temp)

            with self.assertRaises(KeyError):
                service.track("missing-publication")

    def test_add_url_extracts_indexes_and_tracks_in_one_operation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            state = LibraryState(root / ".komaforge" / "state.sqlite")
            service = LibraryService(index, state)
            received = []

            def runner(args):
                received.append(args)
                write_manifest(
                    root / "One" / "pages.json",
                    "https://example.test/one",
                    "One",
                    "https://cdn.example.test/one.webp",
                )
                return 0

            added = service.add_url(
                "https://example.test/one",
                root,
                options={"language": "fr", "output_format": "original"},
                runner=runner,
            )

            self.assertEqual(added.publication.title, "One")
            self.assertEqual(added.tracked.publication_id, added.publication.id)
            self.assertEqual(received[0].output_root, root.resolve())
            self.assertTrue(received[0].output_auto_named)
            self.assertEqual(len(service.tracked()), 1)

    def test_add_url_does_not_track_a_failed_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            state = LibraryState(root / ".komaforge" / "state.sqlite")
            service = LibraryService(index, state)

            with self.assertRaisesRegex(RuntimeError, "exit code 2"):
                service.add_url(
                    "https://example.test/one",
                    root,
                    runner=lambda _args: 2,
                )

            self.assertEqual(state.tracked(), ())

    def test_progress_must_stay_inside_the_part(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, _, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            part = publication.parts[0]
            service.track(publication.id)

            with self.assertRaisesRegex(ValueError, "exceeds"):
                service.record_progress(publication.id, part.id, 2)

    def test_untracking_removes_its_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, state, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            part = publication.parts[0]
            service.track(publication.id)
            service.record_progress(publication.id, part.id, 1)

            removed = state.untrack(publication.id)

            self.assertTrue(removed)
            self.assertEqual(state.tracked(), ())
            self.assertEqual(state.progress(), ())


if __name__ == "__main__":
    unittest.main()
