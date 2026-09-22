from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from .paths import default_output_dir


DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="document-extractor",
        description=(
            "Détecte et enregistre les pages image d'un document publié sur "
            "un site que vous contrôlez ou êtes autorisé à archiver."
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL du document. Sans URL, un assistant interactif s'ouvre.",
    )
    parser.add_argument("--selector", help="Sélecteur CSS des images (facultatif)")
    parser.add_argument("--expected", type=int, help="Nombre de pages attendu")
    parser.add_argument("--output", type=Path, help="Dossier de sortie")
    parser.add_argument("--reading-mode-selector", help="Contrôle du mode continu")
    parser.add_argument("--reading-mode-value", help="Valeur du mode continu")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--ready-selector", help="Élément indiquant que la page est prête")
    parser.add_argument("--wait-for-user", action="store_true")
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--chrome", default=DEFAULT_CHROME, help="Chemin de Chrome")
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-image-mb", type=int, default=50)
    return parser


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[O/n]" if default else "[o/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"o", "oui", "y", "yes"}


def interactive_setup(args: argparse.Namespace) -> argparse.Namespace:
    print("\nDocument Extractor")
    print("1. Extraction automatique (recommandé)")
    print("2. Extraction avec options avancées")
    print("3. Quitter")
    choice = input("Choix [1] : ").strip() or "1"
    if choice == "3":
        raise SystemExit(0)
    if choice not in {"1", "2"}:
        raise SystemExit("Choix invalide.")

    args.url = input("URL du document : ").strip()
    if not args.url:
        raise SystemExit("Aucune URL fournie.")

    custom_output = input(
        "Dossier de sortie [Entrée = C:\\Extractions\\Manga] : "
    ).strip()
    if custom_output:
        args.output = Path(custom_output).expanduser()
    args.pdf = ask_yes_no("Créer aussi un PDF ?")
    args.wait_for_user = ask_yes_no("Le site demande-t-il une connexion manuelle ?")

    if choice == "2":
        args.selector = input("Sélecteur CSS des pages [auto] : ").strip() or None
        raw_expected = input("Nombre de pages attendu [auto] : ").strip()
        if raw_expected:
            args.expected = int(raw_expected)
        args.reading_mode_selector = (
            input("Sélecteur du mode lecture [auto] : ").strip() or None
        )
        if args.reading_mode_selector:
            args.reading_mode_value = (
                input("Valeur du mode lecture [clic automatique] : ").strip() or None
            )
    return args


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit("L'URL doit commencer par http:// ou https://")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if not args.url:
        if not sys.stdin.isatty():
            raise SystemExit("URL manquante. Ajoutez une URL ou lancez le menu interactif.")
        args = interactive_setup(args)
    validate_url(args.url)
    args.output = (
        args.output.expanduser().resolve()
        if args.output
        else default_output_dir(args.url)
    )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from .engine import run

    print(f"URL : {args.url}")
    print(f"Sortie : {args.output}")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nOpération annulée.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nERREUR : {exc}", file=sys.stderr)
        return 1
