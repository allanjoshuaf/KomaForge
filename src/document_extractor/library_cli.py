from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext, redirect_stdout
from dataclasses import asdict
from pathlib import Path

from .formats import OUTPUT_FORMATS
from .library import LibraryIndex
from .library_service import LibraryService
from .library_state import LibraryState
from .jobs import JobQueue
from .paths import default_output_root
from .terminal_ui import SUPPORTED_LANGUAGES


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=default_output_root(),
        help="Dossier contenant les extractions KomaForge",
    )
    parser.add_argument(
        "--index",
        type=Path,
        help="Fichier SQLite (défaut : ROOT/.komaforge/library.sqlite)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Produit une sortie JSON exploitable par une autre application",
    )


def _add_state_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state",
        type=Path,
        help="État de lecture SQLite (défaut : ROOT/.komaforge/state.sqlite)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge-library",
        description="Reconstruit et consulte l’index local des manifestes KomaForge.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    rebuild = subparsers.add_parser(
        "rebuild",
        help="Reconstruit atomiquement l’index depuis les manifestes",
    )
    _add_paths(rebuild)
    add = subparsers.add_parser(
        "add",
        help="Extrait une URL et ajoute sa publication au suivi",
    )
    add.add_argument("url")
    add.add_argument("--format", choices=OUTPUT_FORMATS, dest="output_format", default="original")
    add.add_argument("--scope", choices=("auto", "document", "work"), default="auto")
    add.add_argument("--chapters", default="all")
    add.add_argument("--language", choices=SUPPORTED_LANGUAGES, default="fr")
    add.add_argument("--workers", type=int, choices=range(1, 13), default=6)
    add.add_argument("--watermarks", choices=("detect", "remove"), default="remove")
    add.add_argument("--allow-host", action="append", default=[])
    _add_paths(add)
    _add_state_path(add)
    listing = subparsers.add_parser(
        "list",
        help="Liste les œuvres déjà indexées",
    )
    _add_paths(listing)
    publications = subparsers.add_parser(
        "publications",
        help="Liste les publications et leurs identifiants de suivi",
    )
    _add_paths(publications)
    downloaded = subparsers.add_parser(
        "downloaded",
        help="Liste les publications dont l’artefact est disponible",
    )
    _add_paths(downloaded)
    open_parser = subparsers.add_parser(
        "open",
        help="Ouvre l’artefact local d’une publication",
    )
    open_parser.add_argument("publication_id")
    _add_paths(open_parser)
    read = subparsers.add_parser(
        "read",
        help="Lit un CBZ ou un dossier d’images dans le lecteur local",
    )
    read.add_argument("publication_id")
    _add_paths(read)
    _add_state_path(read)
    status = subparsers.add_parser("status", help="Résume la santé de la bibliothèque")
    _add_paths(status)
    search = subparsers.add_parser("search", help="Recherche dans la bibliothèque locale")
    search.add_argument("query")
    _add_paths(search)
    track = subparsers.add_parser("track", help="Ajoute une publication à la bibliothèque")
    track.add_argument("publication_id")
    _add_paths(track)
    _add_state_path(track)
    untrack = subparsers.add_parser("untrack", help="Retire une publication suivie")
    untrack.add_argument("publication_id")
    _add_paths(untrack)
    _add_state_path(untrack)
    tracked = subparsers.add_parser("tracked", help="Liste les publications suivies")
    _add_paths(tracked)
    _add_state_path(tracked)
    unread = subparsers.add_parser("unread", help="Liste les parties non terminées")
    unread.add_argument("--publication-id")
    _add_paths(unread)
    _add_state_path(unread)
    history = subparsers.add_parser("history", help="Affiche l’historique de lecture")
    _add_paths(history)
    _add_state_path(history)
    update = subparsers.add_parser(
        "update",
        help="Met les publications suivies en file de vérification",
    )
    update.add_argument("--publication-id")
    update.add_argument(
        "--queue",
        type=Path,
        help="File SQLite (défaut : ROOT/.komaforge/jobs.sqlite)",
    )
    _add_paths(update)
    _add_state_path(update)
    progress = subparsers.add_parser("progress", help="Enregistre la progression de lecture")
    progress.add_argument("publication_id")
    progress.add_argument("part_id")
    progress.add_argument("resource_position", type=int)
    progress.add_argument("--complete", action="store_true")
    _add_paths(progress)
    _add_state_path(progress)
    return parser


def _resolved_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    root = args.root.expanduser().resolve()
    index = (
        args.index.expanduser().resolve()
        if args.index
        else root / ".komaforge" / "library.sqlite"
    )
    return root, index


def _state_path(args: argparse.Namespace, root: Path) -> Path:
    return (
        args.state.expanduser().resolve()
        if getattr(args, "state", None)
        else root / ".komaforge" / "state.sqlite"
    )


def _print_rebuild(summary, index_path: Path, as_json: bool) -> None:
    payload = {**asdict(summary), "index": str(index_path)}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"Index reconstruit : {index_path}")
    print(
        f"{summary.works} œuvre(s), {summary.publications} publication(s), "
        f"{summary.parts} partie(s), {summary.resources} ressource(s)"
    )
    if summary.duplicate_manifests:
        print(
            f"{summary.duplicate_manifests} manifeste(s) en doublon écarté(s) "
            "par priorité d’état, d’intégrité et de date"
        )


def _print_works(works: tuple[dict, ...], as_json: bool) -> None:
    if as_json:
        print(json.dumps(list(works), ensure_ascii=False, sort_keys=True))
        return
    if not works:
        print("Aucune œuvre indexée.")
        return
    for work in works:
        print(
            f"{work['title']} | {work['publication_count']} publication(s) | "
            f"{work['part_count']} partie(s)"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root, index_path = _resolved_paths(args)
    index = LibraryIndex(index_path)
    try:
        if args.command == "rebuild":
            summary = index.rebuild(root)
            _print_rebuild(summary, index_path, args.as_json)
            return 0
        if args.command in {
            "add",
            "track",
            "untrack",
            "tracked",
            "unread",
            "history",
            "update",
            "progress",
            "read",
        }:
            state = LibraryState(_state_path(args, root))
            service = LibraryService(index, state)
            if args.command == "add":
                extraction_output = (
                    redirect_stdout(sys.stderr) if args.as_json else nullcontext()
                )
                with extraction_output:
                    added = service.add_url(
                        args.url,
                        root,
                        options={
                            "allow_host": args.allow_host,
                            "chapters": args.chapters,
                            "language": args.language,
                            "output_format": args.output_format,
                            "scope": args.scope,
                            "watermarks": args.watermarks,
                            "workers": args.workers,
                        },
                    )
                payload = {
                    "publication_id": added.publication.id,
                    "title": added.publication.title,
                    "tracked_at": added.tracked.added_at,
                }
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                else:
                    print(
                        f"Publication ajoutée et suivie : "
                        f"{added.publication.title} ({added.publication.id})"
                    )
                return 0
            index.ensure(root)
            if args.command == "read":
                reader_output = redirect_stdout(sys.stderr) if args.as_json else nullcontext()
                with reader_output:
                    path = service.read_artifact(args.publication_id)
                if args.as_json:
                    print(json.dumps({"path": str(path)}, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"Lecture terminée : {path}")
                return 0
            if args.command == "track":
                tracked = service.track(args.publication_id)
                payload = {
                    "publication_id": tracked.publication_id,
                    "added_at": tracked.added_at,
                }
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"Publication suivie : {tracked.publication_id}")
                return 0
            if args.command == "untrack":
                removed = state.untrack(args.publication_id)
                if args.as_json:
                    print(json.dumps({"removed": removed}, sort_keys=True))
                else:
                    print("Publication retirée." if removed else "Publication non suivie.")
                return 0 if removed else 2
            if args.command == "progress":
                progress = service.record_progress(
                    args.publication_id,
                    args.part_id,
                    args.resource_position,
                    completed=args.complete,
                )
                payload = {
                    "publication_id": progress.publication_id,
                    "part_id": progress.part_id,
                    "resource_position": progress.resource_position,
                    "completed": progress.completed,
                    "updated_at": progress.updated_at,
                }
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                else:
                    print(
                        f"Progression : {progress.part_id} — "
                        f"ressource {progress.resource_position}"
                    )
                return 0

            if args.command == "unread":
                unread_parts = service.unread(args.publication_id)
                payload = [
                    {
                        "publication_id": item.publication.id,
                        "publication_title": item.publication.title,
                        "part_id": item.part.id,
                        "part_title": item.part.title,
                        "part_position": item.part.position,
                        "resource_position": item.resource_position,
                    }
                    for item in unread_parts
                ]
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                elif not payload:
                    print("Aucune partie non lue.")
                else:
                    for item in payload:
                        print(
                            f"{item['publication_title']} | {item['part_title']} | "
                            f"position {item['resource_position']}"
                        )
                return 0

            if args.command == "history":
                history = service.history()
                payload = [
                    {
                        "publication_id": item.publication.id,
                        "publication_title": item.publication.title,
                        "part_id": item.part.id,
                        "part_title": item.part.title,
                        "resource_position": item.progress.resource_position,
                        "completed": item.progress.completed,
                        "updated_at": item.progress.updated_at,
                    }
                    for item in history
                ]
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                elif not payload:
                    print("Aucun historique de lecture.")
                else:
                    for item in payload:
                        print(
                            f"{item['publication_title']} | {item['part_title']} | "
                            f"position {item['resource_position']} | {item['updated_at']}"
                        )
                return 0

            if args.command == "update":
                queue_path = (
                    args.queue.expanduser().resolve()
                    if args.queue
                    else root / ".komaforge" / "jobs.sqlite"
                )
                queued = service.queue_updates(
                    JobQueue(queue_path),
                    args.publication_id,
                )
                payload = {
                    "queued": len(queued),
                    "job_ids": [job.id for job in queued],
                    "queue": str(queue_path),
                }
                if args.as_json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"{len(queued)} vérification(s) ajoutée(s) à la file.")
                return 0

            views = service.tracked()
            payload = [
                {
                    "publication_id": view.publication.id,
                    "title": view.publication.title,
                    "completed_parts": view.completed_parts,
                    "unread_parts": view.unread_parts,
                    "added_at": view.tracked.added_at,
                }
                for view in views
            ]
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            elif not payload:
                print("Aucune publication suivie.")
            else:
                for item in payload:
                    print(
                        f"{item['title']} | {item['unread_parts']} non lue(s) | "
                        f"{item['completed_parts']} terminée(s)"
                    )
            return 0
        index.ensure(root)
        if args.command == "publications":
            publications = index.list_publications()
            if args.as_json:
                print(
                    json.dumps(
                        list(publications),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            elif not publications:
                print("Aucune publication indexée.")
            else:
                for publication in publications:
                    print(
                        f"{publication['id']} | {publication['title']} | "
                        f"{publication['coverage_status'] or 'unknown'}"
                    )
            return 0
        if args.command == "downloaded":
            publications = index.list_downloaded()
            if args.as_json:
                print(json.dumps(list(publications), ensure_ascii=False, sort_keys=True))
            elif not publications:
                print("Aucune publication téléchargée.")
            else:
                for publication in publications:
                    print(
                        f"{publication['title']} | "
                        f"{publication['artifact_integrity']}"
                    )
            return 0
        if args.command == "open":
            path = LibraryService(
                index,
                LibraryState(root / ".komaforge" / "state.sqlite"),
            ).open_artifact(args.publication_id)
            if args.as_json:
                print(json.dumps({"path": str(path)}, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Ouvert : {path}")
            return 0
        if args.command == "status":
            status = index.status()
            if args.as_json:
                print(json.dumps(status, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    f"{status['works']} œuvre(s), {status['publications']} publication(s), "
                    f"{status['parts']} partie(s), {status['resources']} ressource(s)"
                )
                print(f"Intégrité : {status['artifact_integrity']}")
                print(f"Couverture : {status['coverage']}")
                print(f"État des manifestes : {status['legacy_status']}")
            return 0
        works = (
            index.search_works(args.query)
            if args.command == "search"
            else index.list_works()
        )
        _print_works(works, args.as_json)
        return 0
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(f"Erreur de bibliothèque : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
