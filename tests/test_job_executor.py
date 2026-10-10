from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from document_extractor.job_executor import JobExecutor
from document_extractor.jobs import JobAction, JobQueue, JobStatus
from document_extractor.library import LibraryIndex
from document_extractor.library_state import LibraryState


class JobExecutorTests(unittest.TestCase):
    def test_inspect_job_uses_the_existing_cli_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queued = queue.enqueue(
                JobAction.INSPECT,
                "https://example.test/book",
                options={"scope": "document", "workers": 2},
            )
            received = []

            def runner(args):
                received.append(args)
                return 0

            result = JobExecutor(queue, runner).run_next()

            self.assertEqual(result.id, queued.id)
            self.assertEqual(result.status, JobStatus.COMPLETED)
            self.assertTrue(received[0].inspect)
            self.assertEqual(received[0].scope, "document")
            self.assertEqual(received[0].workers, 2)

    def test_nonzero_exit_marks_the_job_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/book")

            result = JobExecutor(queue, lambda args: 2).run_next()

            self.assertEqual(result.status, JobStatus.FAILED)
            self.assertEqual(result.last_error, "execution returned exit code 2")

    def test_queue_under_custom_library_routes_auto_named_output_there(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "custom-library"
            queue = JobQueue(root / ".komaforge" / "jobs.sqlite")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/book")
            received = []

            result = JobExecutor(
                queue,
                lambda args: received.append(args) or 0,
            ).run_next()

            self.assertEqual(result.status, JobStatus.COMPLETED)
            self.assertEqual(received[0].output_root, root.resolve())
            self.assertEqual(
                received[0].output,
                root.resolve() / ".komaforge" / "incoming",
            )
            self.assertTrue(received[0].output_auto_named)

    def test_explicit_job_output_is_not_replaced_by_library_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "custom-library"
            explicit = Path(temp) / "chosen-output"
            queue = JobQueue(root / ".komaforge" / "jobs.sqlite")
            queue.enqueue(
                JobAction.DOWNLOAD,
                "https://example.test/book",
                options={"output": str(explicit)},
            )
            received = []

            JobExecutor(queue, lambda args: received.append(args) or 0).run_next()

            self.assertEqual(received[0].output, explicit.resolve())
            self.assertEqual(received[0].output_root, explicit.resolve())
            self.assertFalse(received[0].output_auto_named)

    def test_runner_exception_does_not_persist_its_sensitive_message(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/book")

            def runner(args):
                raise RuntimeError("https://reader.example/?token=secret")

            result = JobExecutor(queue, runner).run_next()

            self.assertEqual(result.status, JobStatus.FAILED)
            self.assertEqual(result.last_error, "execution failed: RuntimeError")

    def test_update_job_inspects_and_enqueues_only_new_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest_path = root / "Book" / "publication.json"
            manifest_path.parent.mkdir(parents=True)

            def manifest(chapters):
                return {
                    "source_url": "https://example.test/book",
                    "publication": {
                        "type": "work",
                        "title": "Book",
                        "part_count": len(chapters),
                        "selected_part_count": len(chapters),
                        "status": "complete",
                        "chapters": chapters,
                    },
                }

            def chapter(number):
                return {
                    "index": number,
                    "number": str(number),
                    "title": f"Chapter {number}",
                    "kind": "chapter",
                    "source_url": f"https://example.test/book/chapter-{number}",
                    "status": "complete",
                    "detected": 1,
                    "expected": 1,
                    "pages": [],
                }

            manifest_path.write_text(
                json.dumps(manifest([chapter(1)])),
                encoding="utf-8",
            )
            index = LibraryIndex(root / ".komaforge" / "library.sqlite")
            index.rebuild(root)
            publication_id = index.list_publications()[0]["id"]
            state = LibraryState(root / ".komaforge" / "state.sqlite")
            state.track(publication_id)
            queue = JobQueue(root / ".komaforge" / "jobs.sqlite")
            queued = queue.enqueue(
                JobAction.UPDATE,
                "https://example.test/book",
                options={"language": "fr"},
            )
            queue.enqueue(
                JobAction.UPDATE,
                "https://example.test/book",
                options={"language": "fr"},
            )

            downloads = []

            def runner(args):
                if args.inspect:
                    args.inspection_manifest = manifest(
                        [chapter(1), chapter(2), chapter(3)]
                    )
                else:
                    downloads.append(args)
                return 0

            result = JobExecutor(queue, runner).run_next()

            jobs = queue.list()
            self.assertEqual(result.id, queued.id)
            self.assertEqual(result.status, JobStatus.COMPLETED)
            self.assertEqual(len(jobs), 3)
            download = next(job for job in jobs if job.action is JobAction.DOWNLOAD)
            self.assertEqual(download.action, JobAction.DOWNLOAD)
            self.assertEqual(
                download.source_url,
                "https://example.test/book",
            )
            self.assertEqual(download.options["scope"], "work")
            self.assertEqual(download.options["chapters"], "2,3")
            self.assertEqual(download.status, JobStatus.PENDING)
            updates = state.updates(unseen_only=True)
            self.assertEqual(len(updates), 2)
            self.assertTrue(
                all(update.publication_id == publication_id for update in updates)
            )
            self.assertEqual(
                {update.part_title for update in updates},
                {"Chapter 2", "Chapter 3"},
            )
            self.assertTrue(
                all(update.download_job_id == download.id for update in updates)
            )

            repeated = JobExecutor(queue, runner).run_next()

            self.assertEqual(repeated.status, JobStatus.COMPLETED)
            self.assertEqual(
                len(
                    [
                        job
                        for job in queue.list()
                        if job.action is JobAction.DOWNLOAD
                    ]
                ),
                1,
            )
            self.assertEqual(len(state.updates()), 2)

            downloaded = JobExecutor(queue, runner).run_next()

            self.assertEqual(downloaded.status, JobStatus.COMPLETED)
            self.assertEqual(downloads[0].output_root, root.resolve())
            self.assertEqual(
                downloads[0].output,
                root.resolve() / ".komaforge" / "incoming",
            )
            self.assertEqual(downloads[0].scope, "work")
            self.assertEqual(downloads[0].chapters, "2,3")

    def test_unsupported_options_fail_without_starting_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(
                JobAction.DOWNLOAD,
                "https://example.test/book",
                options={"wait_for_user": True},
            )
            calls = []

            result = JobExecutor(queue, lambda args: calls.append(args) or 0).run_next()

            self.assertEqual(result.status, JobStatus.FAILED)
            self.assertEqual(calls, [])

    def test_update_job_with_no_new_parts_enqueues_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {
                "source_url": "https://example.test/book",
                "publication": {
                    "type": "work",
                    "title": "Book",
                    "part_count": 1,
                    "selected_part_count": 1,
                    "status": "complete",
                    "chapters": [
                        {
                            "index": 1,
                            "number": "1",
                            "title": "Chapter 1",
                            "kind": "chapter",
                            "source_url": "https://example.test/book/chapter-1",
                            "status": "complete",
                            "detected": 1,
                            "expected": 1,
                            "pages": [],
                        }
                    ],
                },
            }
            manifest_path = root / "Book" / "publication.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            queue = JobQueue(root / ".komaforge" / "jobs.sqlite")
            queue.enqueue(JobAction.UPDATE, "https://example.test/book")

            def runner(args):
                args.inspection_manifest = manifest
                return 0

            result = JobExecutor(queue, runner).run_next()

            self.assertEqual(result.status, JobStatus.COMPLETED)
            self.assertEqual(len(queue.list()), 1)

    def test_run_all_drains_executable_jobs_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(JobAction.INSPECT, "https://example.test/one")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/two")
            calls = []

            jobs = JobExecutor(
                queue,
                lambda args: calls.append(args.url) or 0,
            ).run_all()

            self.assertEqual(len(jobs), 2)
            self.assertEqual(
                calls,
                ["https://example.test/one", "https://example.test/two"],
            )
            self.assertTrue(all(job.status is JobStatus.COMPLETED for job in jobs))

    def test_run_all_limit_leaves_remaining_jobs_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/one")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/two")

            jobs = JobExecutor(queue, lambda _args: 0).run_all(limit=1)

            self.assertEqual(len(jobs), 1)
            self.assertEqual(
                [job.status for job in queue.list()],
                [JobStatus.COMPLETED, JobStatus.PENDING],
            )

    def test_run_all_can_leave_unrelated_actions_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queue.enqueue(JobAction.INSPECT, "https://example.test/inspect")
            queue.enqueue(JobAction.DOWNLOAD, "https://example.test/download")
            calls = []

            jobs = JobExecutor(
                queue,
                lambda args: calls.append(args.url) or 0,
            ).run_all(actions=(JobAction.UPDATE, JobAction.DOWNLOAD))

            self.assertEqual(calls, ["https://example.test/download"])
            self.assertEqual([job.action for job in jobs], [JobAction.DOWNLOAD])
            self.assertEqual(
                [job.status for job in queue.list()],
                [JobStatus.PENDING, JobStatus.COMPLETED],
            )


if __name__ == "__main__":
    unittest.main()
