from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from document_extractor.jobs import JobAction, JobQueue, JobStatus


class JobQueueTests(unittest.TestCase):
    def test_jobs_persist_across_queue_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "jobs.sqlite"
            created = JobQueue(path).enqueue(
                JobAction.INSPECT,
                "https://example.test/book",
                options={"scope": "document"},
            )

            loaded = JobQueue(path).list()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, created.id)
            self.assertEqual(loaded[0].source_id, "generic-web")
            self.assertEqual(loaded[0].options, {"scope": "document"})

    def test_temporary_or_credentialed_urls_are_never_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")

            with self.assertRaisesRegex(ValueError, "temporary session"):
                queue.enqueue(
                    JobAction.DOWNLOAD,
                    "https://example.test/book?_token_=secret",
                )
            with self.assertRaisesRegex(ValueError, "credentials"):
                queue.enqueue(
                    JobAction.DOWNLOAD,
                    "https://reader:secret@example.test/book",
                )
            with self.assertRaisesRegex(ValueError, "product URL"):
                queue.enqueue(
                    JobAction.DOWNLOAD,
                    "https://reader.ebooks.com/preview?bid=347114076",
                )

            self.assertFalse(queue.path.exists())

    def test_ebooks_product_url_is_safe_to_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")

            job = queue.enqueue(
                JobAction.INSPECT,
                "https://www.ebooks.com/en-us/book/347114076/example/author/",
            )

            self.assertEqual(job.source_id, "ebooks")
            self.assertEqual(job.status, JobStatus.PENDING)

    def test_claim_complete_and_illegal_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            pending = queue.enqueue(
                JobAction.DOWNLOAD,
                "https://example.test/book",
            )

            running = queue.claim_next()
            completed = queue.complete(running.id)

            self.assertEqual(running.id, pending.id)
            self.assertEqual(running.status, JobStatus.RUNNING)
            self.assertEqual(running.attempts, 1)
            self.assertEqual(completed.status, JobStatus.COMPLETED)
            self.assertIsNone(queue.claim_next())
            with self.assertRaisesRegex(RuntimeError, "cannot move"):
                queue.cancel(completed.id)

    def test_failed_job_can_be_retried_and_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            job = queue.enqueue(JobAction.UPDATE, "https://example.test/book")
            running = queue.claim_next()

            pending = queue.fail(running.id, "network unavailable", retry=True)
            running_again = queue.claim_next()
            recovered_count = queue.recover_interrupted()

            self.assertEqual(pending.status, JobStatus.PENDING)
            self.assertEqual(pending.last_error, "network unavailable")
            self.assertEqual(running_again.attempts, 2)
            self.assertEqual(recovered_count, 1)
            self.assertEqual(queue.list()[0].status, JobStatus.PENDING)

    def test_cancelled_job_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = JobQueue(Path(temp) / "jobs.sqlite")
            job = queue.enqueue(JobAction.INSPECT, "https://example.test/book")

            cancelled = queue.cancel(job.id)

            self.assertEqual(cancelled.status, JobStatus.CANCELLED)
            self.assertIsNone(queue.claim_next())


if __name__ == "__main__":
    unittest.main()
