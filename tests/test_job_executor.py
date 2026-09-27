from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from document_extractor.job_executor import JobExecutor
from document_extractor.jobs import JobAction, JobQueue, JobStatus


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

            def runner(args):
                self.assertTrue(args.inspect)
                args.inspection_manifest = manifest([chapter(1), chapter(2)])
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
                "https://example.test/book/chapter-2",
            )
            self.assertEqual(download.status, JobStatus.PENDING)

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


if __name__ == "__main__":
    unittest.main()
