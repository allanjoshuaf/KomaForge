from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from document_extractor.jobs_cli import main


class JobsCliTests(unittest.TestCase):
    def test_run_next_forwards_an_explicit_library_root(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = Path(temp) / "jobs.sqlite"
            root = Path(temp) / "library"
            with patch("document_extractor.jobs_cli.JobExecutor") as executor:
                executor.return_value.run_next.return_value = None
                with redirect_stdout(StringIO()):
                    code = main(
                        [
                            "run-next",
                            "--queue",
                            str(queue),
                            "--root",
                            str(root),
                            "--json",
                        ]
                    )

            self.assertEqual(code, 2)
            self.assertEqual(
                executor.call_args.kwargs["library_root"],
                root,
            )

    def test_add_list_and_cancel_json(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = Path(temp) / "jobs.sqlite"
            added_output = StringIO()
            with redirect_stdout(added_output):
                added_code = main(
                    [
                        "add",
                        "https://example.test/book",
                        "--action",
                        "inspect",
                        "--format",
                        "epub",
                        "--scope",
                        "document",
                        "--chapters",
                        "1-3",
                        "--workers",
                        "2",
                        "--allow-host",
                        "cdn.example.test",
                        "--queue",
                        str(queue),
                        "--json",
                    ]
                )
            added = json.loads(added_output.getvalue())

            listed_output = StringIO()
            with redirect_stdout(listed_output):
                listed_code = main(
                    [
                        "list",
                        "--status",
                        "pending",
                        "--queue",
                        str(queue),
                        "--json",
                    ]
                )
            listed = json.loads(listed_output.getvalue())

            cancelled_output = StringIO()
            with redirect_stdout(cancelled_output):
                cancelled_code = main(
                    [
                        "cancel",
                        added["id"],
                        "--queue",
                        str(queue),
                        "--json",
                    ]
                )
            cancelled = json.loads(cancelled_output.getvalue())

            self.assertEqual(added_code, 0)
            self.assertEqual(added["action"], "inspect")
            self.assertEqual(
                added["options"],
                {
                    "allow_host": ["cdn.example.test"],
                    "chapters": "1-3",
                    "output_format": "epub",
                    "scope": "document",
                    "workers": 2,
                },
            )
            self.assertEqual(listed_code, 0)
            self.assertEqual([job["id"] for job in listed], [added["id"]])
            self.assertEqual(cancelled_code, 0)
            self.assertEqual(cancelled["status"], "cancelled")

    def test_add_rejects_session_url_without_creating_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = Path(temp) / "jobs.sqlite"
            error = StringIO()

            with redirect_stderr(error):
                code = main(
                    [
                        "add",
                        "https://example.test/book?token=secret",
                        "--queue",
                        str(queue),
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("stable publication URL", error.getvalue())
            self.assertFalse(queue.exists())

    def test_retry_requeues_a_failed_job(self):
        with tempfile.TemporaryDirectory() as temp:
            queue_path = Path(temp) / "jobs.sqlite"
            from document_extractor.jobs import JobAction, JobQueue

            queue = JobQueue(queue_path)
            job = queue.enqueue(JobAction.INSPECT, "https://example.test/book")
            queue.claim_next()
            queue.fail(job.id, "temporary")
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    ["retry", job.id, "--queue", str(queue_path), "--json"]
                )
            retried = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(retried["status"], "pending")
            self.assertEqual(retried["attempts"], 1)
            self.assertIsNone(retried["last_error"])


if __name__ == "__main__":
    unittest.main()
