from __future__ import annotations

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

    def test_update_job_remains_pending_until_update_logic_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            queued = queue.enqueue(JobAction.UPDATE, "https://example.test/book")

            result = JobExecutor(queue, lambda args: 0).run_next()

            self.assertIsNone(result)
            self.assertEqual(queue.list()[0].id, queued.id)
            self.assertEqual(queue.list()[0].status, JobStatus.PENDING)

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


if __name__ == "__main__":
    unittest.main()
