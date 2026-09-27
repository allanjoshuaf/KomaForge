from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .library import SCHEMA_VERSION, LibraryIndex
from .paths import default_output_root


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
    listing = subparsers.add_parser(
        "list",
        help="Liste les œuvres déjà indexées",
    )
    _add_paths(listing)
    return parser


def _resolved_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    root = args.root.expanduser().resolve()
    index = (
        args.index.expanduser().resolve()
        if args.index
        else root / ".komaforge" / "library.sqlite"
    )
    return root, index


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
        if index.schema_version() != SCHEMA_VERSION:
            print(
                "Index absent ou incompatible. Lancez d’abord "
                "`komaforge-library rebuild`.",
                file=sys.stderr,
            )
            return 2
        _print_works(index.list_works(), args.as_json)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Erreur de bibliothèque : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
