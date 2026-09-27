from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .formats import OUTPUT_FORMATS
from .job_executor import JobExecutor
from .jobs import Job, JobAction, JobQueue, JobStatus
from .paths import default_output_root
from .terminal_ui import SUPPORTED_LANGUAGES


def _default_queue_path() -> Path:
    return default_output_root() / ".komaforge" / "jobs.sqlite"


def _add_queue_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--queue",
        type=Path,
        default=_default_queue_path(),
        help="Fichier SQLite de la file persistante",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge-jobs",
        description="Gère les travaux persistants de KomaForge.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="Ajoute un travail à la file")
    add.add_argument("url", help="URL stable de la publication")
    add.add_argument(
        "--action",
        choices=tuple(action.value for action in JobAction),
        default=JobAction.DOWNLOAD.value,
    )
    add.add_argument("--format", choices=OUTPUT_FORMATS, dest="output_format")
    add.add_argument("--scope", choices=("auto", "document", "work"))
    add.add_argument("--chapters")
    add.add_argument("--output", type=Path)
    add.add_argument("--expected", type=int)
    add.add_argument("--selector")
    add.add_argument("--language", choices=SUPPORTED_LANGUAGES)
    add.add_argument("--workers", type=int, choices=range(1, 13), metavar="1-12")
    add.add_argument("--watermarks", choices=("detect", "remove"))
    add.add_argument("--allow-host", action="append", default=[])
    add.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(add)

    listing = commands.add_parser("list", help="Liste les travaux")
    listing.add_argument(
        "--status",
        choices=tuple(status.value for status in JobStatus),
    )
    listing.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(listing)

    cancel = commands.add_parser("cancel", help="Annule un travail en attente")
    cancel.add_argument("job_id")
    cancel.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(cancel)

    retry = commands.add_parser("retry", help="Replace un travail échoué en attente")
    retry.add_argument("job_id")
    retry.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(retry)

    recover = commands.add_parser(
        "recover",
        help="Replace en attente les travaux interrompus pendant leur exécution",
    )
    recover.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(recover)

    run_next = commands.add_parser(
        "run-next",
        help="Exécute le prochain travail inspect, download ou update",
    )
    run_next.add_argument("--json", action="store_true", dest="as_json")
    _add_queue_path(run_next)
    return parser


def _payload(job: Job) -> dict:
    return {
        "id": job.id,
        "action": job.action.value,
        "source_id": job.source_id,
        "source_url": job.source_url,
        "status": job.status.value,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "attempts": job.attempts,
        "options": dict(job.options or {}),
        "last_error": job.last_error,
    }


def _print_job(job: Job, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_payload(job), ensure_ascii=False, sort_keys=True))
        return
    print(f"{job.id} | {job.status.value} | {job.action.value} | {job.source_id}")


def _options_from_args(args: argparse.Namespace) -> dict:
    options = {}
    for key in (
        "chapters",
        "expected",
        "language",
        "output_format",
        "scope",
        "selector",
        "watermarks",
        "workers",
    ):
        value = getattr(args, key, None)
        if value is not None:
            options[key] = value
    if args.output is not None:
        options["output"] = str(args.output.expanduser())
    if args.allow_host:
        options["allow_host"] = list(args.allow_host)
    return options


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    queue = JobQueue(args.queue)
    try:
        if args.command == "add":
            job = queue.enqueue(
                JobAction(args.action),
                args.url,
                options=_options_from_args(args),
            )
            _print_job(job, args.as_json)
            return 0
        if args.command == "cancel":
            job = queue.cancel(args.job_id)
            _print_job(job, args.as_json)
            return 0
        if args.command == "retry":
            job = queue.retry(args.job_id)
            _print_job(job, args.as_json)
            return 0
        if args.command == "recover":
            count = queue.recover_interrupted()
            if args.as_json:
                print(json.dumps({"recovered": count}, sort_keys=True))
            else:
                print(f"{count} travail/travaux replacé(s) en attente")
            return 0
        if args.command == "run-next":
            job = JobExecutor(queue).run_next()
            if job is None:
                if args.as_json:
                    print(json.dumps({"executed": False}, sort_keys=True))
                else:
                    print("Aucun travail inspect, download ou update en attente.")
                return 2
            _print_job(job, args.as_json)
            return 0 if job.status is JobStatus.COMPLETED else 1

        status = JobStatus(args.status) if args.status else None
        jobs = queue.list(status)
        if args.as_json:
            print(
                json.dumps(
                    [_payload(job) for job in jobs],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        elif not jobs:
            print("Aucun travail dans la file.")
        else:
            for job in jobs:
                _print_job(job, False)
        return 0
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(f"Erreur de file : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
