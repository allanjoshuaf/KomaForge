from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from document_extractor.library import LibraryIndex
from document_extractor.library_service import LibraryService
from document_extractor.library_state import LibraryState
from document_extractor.jobs import JobAction, JobQueue

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

    def test_version_one_state_is_migrated_without_losing_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE state_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO state_metadata VALUES('schema_version', '1');
                    CREATE TABLE tracked_publications(
                        publication_id TEXT PRIMARY KEY, added_at TEXT NOT NULL
                    );
                    CREATE TABLE reading_progress(
                        part_id TEXT PRIMARY KEY,
                        publication_id TEXT NOT NULL,
                        resource_position INTEGER NOT NULL,
                        completed INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(publication_id)
                            REFERENCES tracked_publications(publication_id)
                            ON DELETE CASCADE
                    );
                    INSERT INTO tracked_publications VALUES('publication-one', 'then');
                    INSERT INTO reading_progress VALUES(
                        'part-one', 'publication-one', 7, 0, 'then'
                    );
                    """
                )
                connection.commit()
            state = LibraryState(path)

            category = state.create_category("À lire")

            self.assertEqual(category.name, "À lire")
            self.assertEqual(state.tracked()[0].publication_id, "publication-one")
            self.assertEqual(state.progress()[0].resource_position, 7)
            with closing(sqlite3.connect(path)) as connection:
                version = connection.execute(
                    "SELECT value FROM state_metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertEqual(version, "2")

    def test_categories_are_casefolded_and_assign_only_tracked_publications(self):
        with tempfile.TemporaryDirectory() as temp:
            state = LibraryState(Path(temp) / "state.sqlite")
            state.track("publication-one")

            first = state.assign_category("publication-one", "  À   lire  ")
            second = state.create_category("à LIRE")

            self.assertEqual(first.id, second.id)
            self.assertEqual(first.name, "À lire")
            self.assertEqual(state.category_members("À LIRE"), ("publication-one",))
            self.assertEqual(state.publication_categories("publication-one"), (first,))
            with self.assertRaisesRegex(ValueError, "must be tracked"):
                state.assign_category("missing", "À lire")

    def test_category_memberships_follow_untrack_and_category_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            state = LibraryState(Path(temp) / "state.sqlite")
            state.track("publication-one")
            state.track("publication-two")
            state.assign_category("publication-one", "Favoris")
            state.assign_category("publication-two", "Favoris")

            self.assertTrue(state.remove_category("publication-two", "favoris"))
            self.assertEqual(state.category_members("Favoris"), ("publication-one",))
            self.assertTrue(state.untrack("publication-one"))
            self.assertEqual(state.category_members("Favoris"), ())
            self.assertTrue(state.delete_category("FAVORIS"))
            self.assertEqual(state.categories(), ())

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

    def test_unread_lists_partial_parts_and_hides_completed_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, _, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            part = publication.parts[0]
            service.track(publication.id)

            initial = service.unread()
            service.record_progress(publication.id, part.id, 1, completed=False)
            partial = service.unread(publication.id)
            service.record_progress(publication.id, part.id, 1, completed=True)
            completed = service.unread(publication.id)

            self.assertEqual(initial[0].resource_position, 0)
            self.assertEqual(partial[0].resource_position, 1)
            self.assertEqual(completed, ())

    def test_unread_rejects_an_untracked_publication_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, service = self._service(temp)

            with self.assertRaises(KeyError):
                service.unread("missing-publication")

    def test_queue_updates_adds_each_tracked_publication_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, _, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            service.track(publication.id)
            queue = JobQueue(Path(temp) / "jobs.sqlite")

            first = service.queue_updates(queue)
            second = service.queue_updates(queue)

            self.assertEqual(len(first), 1)
            self.assertEqual(first[0].action, JobAction.UPDATE)
            self.assertEqual(second, ())
            self.assertEqual(len(queue.list()), 1)

    def test_queue_updates_can_target_one_tracked_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, _, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            service.track(publication.id)
            queue = JobQueue(Path(temp) / "jobs.sqlite")

            queued = service.queue_updates(queue, publication.id)

            self.assertEqual(len(queued), 1)
            with self.assertRaises(KeyError):
                service.queue_updates(queue, "missing-publication")

    def test_history_resolves_progress_back_to_publication_and_part(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, _, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            part = publication.parts[0]
            service.track(publication.id)
            service.record_progress(publication.id, part.id, 1)

            history = service.history()

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].publication.id, publication.id)
            self.assertEqual(history[0].part.id, part.id)
            self.assertEqual(history[0].progress.resource_position, 1)

    def test_service_resolves_category_members_to_current_publications(self):
        with tempfile.TemporaryDirectory() as temp:
            _, index, state, service = self._service(temp)
            publication = index.load_publication(next(index.iter_publications())["id"])
            service.track(publication.id)
            state.assign_category(publication.id, "En cours")

            categorized = service.categorized("en COURS")

            self.assertEqual([item.id for item in categorized], [publication.id])
            self.assertEqual(service.tracked()[0].categories[0].name, "En cours")

    def test_open_artifact_uses_the_validated_local_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            manifest = root / "One" / "pages.json"
            write_manifest(
                manifest,
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            artifact = manifest.parent / "one.cbz"
            artifact.write_bytes(b"archive")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["artifact"] = {"path": artifact.name}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            service = LibraryService(
                index,
                LibraryState(root / ".komaforge" / "state.sqlite"),
            )
            publication = index.list_publications()[0]
            opened = []

            path = service.open_artifact(
                publication["id"],
                opener=opened.append,
            )

            self.assertEqual(path, artifact.resolve())
            self.assertEqual(opened, [artifact.resolve()])

    def test_read_artifact_tracks_and_persists_reader_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outputs"
            manifest = root / "One" / "pages.json"
            write_manifest(
                manifest,
                "https://example.test/one",
                "One",
                "https://cdn.example.test/one.webp",
            )
            artifact = manifest.parent / "one.cbz"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("page-0001.webp", b"page")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["artifact"] = {"path": artifact.name}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            state = LibraryState(root / ".komaforge" / "state.sqlite")
            service = LibraryService(index, state)
            publication = index.load_publication(index.list_publications()[0]["id"])
            launched = []

            def launcher(document, **options):
                launched.append((document, options))
                options["progress_callback"](1, True)

            path = service.read_artifact(publication.id, launcher=launcher)

            self.assertEqual(path, artifact.resolve())
            self.assertEqual(launched[0][0].pages[0].name, "page-0001.webp")
            self.assertEqual(launched[0][1]["start_position"], 1)
            self.assertEqual(state.tracked()[0].publication_id, publication.id)
            self.assertTrue(state.progress(publication.id)[0].completed)


if __name__ == "__main__":
    unittest.main()
