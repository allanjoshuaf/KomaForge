"""Execution boundary between persistent jobs and the proven extraction engine."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

from .cli import parse_args
from .jobs import Job, JobAction, JobQueue


JobRunner = Callable[[Namespace], int]
EXECUTABLE_ACTIONS = (JobAction.INSPECT, JobAction.DOWNLOAD)


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
    if job.action is JobAction.INSPECT:
        arguments.append("--inspect")
    return arguments


def _default_runner(args: Namespace) -> int:
    from .engine import run

    return run(args)


class JobExecutor:
    def __init__(self, queue: JobQueue, runner: JobRunner | None = None) -> None:
        self.queue = queue
        self.runner = runner or _default_runner

    def run_next(self) -> Job | None:
        job = self.queue.claim_next(EXECUTABLE_ACTIONS)
        if job is None:
            return None
        try:
            args = parse_args(_arguments_for(job))
            exit_code = self.runner(args)
        except Exception as exc:
            return self.queue.fail(
                job.id,
                f"execution failed: {type(exc).__name__}",
            )
        if exit_code == 0:
            return self.queue.complete(job.id)
        return self.queue.fail(job.id, f"execution returned exit code {exit_code}")
