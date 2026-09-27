"""Execution boundary between persistent jobs and the proven extraction engine."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

from .cli import parse_args
from .legacy_bridge import normalize_legacy_manifest
from .library import LibraryIndex
from .jobs import Job, JobAction, JobQueue, JobStatus
from .paths import canonical_source_identity, default_output_root
from .updates import compare_part_updates


JobRunner = Callable[[Namespace], int]
EXECUTABLE_ACTIONS = (JobAction.INSPECT, JobAction.DOWNLOAD, JobAction.UPDATE)


def _append_option(arguments: list[str], flag: str, value: object) -> None:
    if isinstance(value, bool):
        if value:
            arguments.append(flag)
        return
    arguments.extend((flag, str(value)))


def _arguments_for(job: Job) -> list[str]:
    arguments = [job.source_url]
    options = dict(job.options or {})
    supported = {
        "allow_host",
        "chapters",
        "expected",
        "language",
        "output",
        "output_format",
        "scope",
        "selector",
        "watermarks",
        "workers",
    }
    unknown = sorted(set(options) - supported)
    if unknown:
        raise ValueError(f"unsupported job option(s): {', '.join(unknown)}")

    scalar_flags = {
        "chapters": "--chapters",
        "expected": "--expected",
        "language": "--language",
        "output": "--output",
        "output_format": "--format",
        "scope": "--scope",
        "selector": "--selector",
        "watermarks": "--watermarks",
        "workers": "--workers",
    }
    for key, flag in scalar_flags.items():
        if key in options and options[key] is not None:
            _append_option(arguments, flag, options[key])
    allow_hosts = options.get("allow_host") or ()
    if isinstance(allow_hosts, str) or not isinstance(allow_hosts, (list, tuple)):
        raise ValueError("allow_host must be a list of host names")
    for host in allow_hosts:
        _append_option(arguments, "--allow-host", host)
    if job.action in {JobAction.INSPECT, JobAction.UPDATE}:
        arguments.append("--inspect")
    return arguments


def _default_runner(args: Namespace) -> int:
    from .engine import run

    return run(args)


class JobExecutor:
    def __init__(
        self,
        queue: JobQueue,
        runner: JobRunner | None = None,
        *,
        library_root: Path | None = None,
    ) -> None:
        self.queue = queue
        self.runner = runner or _default_runner
        self.library_root = (
            library_root.expanduser().resolve()
            if library_root is not None
            else self._infer_library_root()
        )

    def _infer_library_root(self) -> Path:
        parent = self.queue.path.parent
        if parent.name.casefold() == ".komaforge":
            return parent.parent
        return default_output_root()

    def _enqueue_updates(self, job: Job, args: Namespace) -> None:
        index = LibraryIndex(
            self.library_root / ".komaforge" / "library.sqlite"
        )
        index.ensure(self.library_root)
        known = index.find_publication_by_url(job.source_url)
        if known is None:
            raise ValueError("publication is not present in the local library")
        payload = getattr(args, "inspection_manifest", None)
        if not isinstance(payload, dict):
            raise RuntimeError("update inspection produced no structured result")
        current_work = normalize_legacy_manifest(
            payload,
            known.source_id,
            title_hint=known.title,
        )
        current = next(
            (
                publication
                for publication in current_work.publications
                if canonical_source_identity(publication.source_url)
                == canonical_source_identity(known.source_url)
            ),
            None,
        )
        if current is None:
            raise RuntimeError("update inspection returned a different publication")
        result = compare_part_updates(known, known.parts, current.parts)
        base_options = {
            key: value
            for key, value in dict(job.options or {}).items()
            if key
            in {
                "allow_host",
                "language",
                "output_format",
                "watermarks",
                "workers",
            }
        }
        base_options.setdefault("output_format", "original")
        seen_urls: set[str] = set()
        active_downloads = {
            canonical_source_identity(queued.source_url)
            for queued in self.queue.list()
            if queued.action is JobAction.DOWNLOAD
            and queued.status in {JobStatus.PENDING, JobStatus.RUNNING}
        }
        for part in result.parts:
            identity = canonical_source_identity(part.source_url)
            if identity in seen_urls or identity in active_downloads:
                continue
            seen_urls.add(identity)
            options = {**base_options, "scope": "document", "chapters": "all"}
            self.queue.enqueue(JobAction.DOWNLOAD, part.source_url, options=options)
            active_downloads.add(identity)

    def run_next(self) -> Job | None:
        job = self.queue.claim_next(EXECUTABLE_ACTIONS)
        if job is None:
            return None
        try:
            args = parse_args(_arguments_for(job))
            exit_code = self.runner(args)
            if exit_code == 0 and job.action is JobAction.UPDATE:
                self._enqueue_updates(job, args)
        except Exception as exc:
            return self.queue.fail(
                job.id,
                f"execution failed: {type(exc).__name__}",
            )
        if exit_code == 0:
            return self.queue.complete(job.id)
        return self.queue.fail(job.id, f"execution returned exit code {exit_code}")

    def run_all(self, *, limit: int = 100) -> tuple[Job, ...]:
        """Drain executable jobs, including downloads created by update checks."""

        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        completed: list[Job] = []
        for _ in range(limit):
            job = self.run_next()
            if job is None:
                break
            completed.append(job)
        return tuple(completed)
