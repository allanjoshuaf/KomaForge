from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from .paths import default_output_dir
from .formats import OUTPUT_FORMATS


DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge",
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
    parser.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        dest="output_format",
        help="Sortie unique : cbz, cbr, pdf, epub ou images (défaut : cbz)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Alias historique de --format pdf",
    )
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-image-mb", type=int, default=50)
    parser.add_argument(
        "--watermarks",
        choices=("detect", "remove"),
        default="detect",
        help=(
            "SVG : détecter les filigranes, ou retirer automatiquement seulement "
            "les candidats à confiance élevée sur des documents autorisés"
        ),
    )
    return parser


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[O/n]" if default else "[o/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"o", "oui", "y", "yes"}


def interactive_setup(args: argparse.Namespace) -> argparse.Namespace:
    print("\nKomaForge")
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
    print("\nFormat de sortie — un seul fichier ou dossier sera conservé :")
    print("1. CBZ — images originales, recommandé pour manga/BD")
    print("2. CBR — archive RAR, demande WinRAR/rar")
    print("3. PDF — mise en pages fixe")
    print("4. EPUB — livre numérique à mise en pages fixe")
    print("5. Images — fichiers originaux dans un dossier")
    format_choice = input("Format [1] : ").strip() or "1"
    format_map = {"1": "cbz", "2": "cbr", "3": "pdf", "4": "epub", "5": "images"}
    if format_choice not in format_map:
        raise SystemExit("Format invalide.")
    args.output_format = format_map[format_choice]
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
        args.watermarks = (
            input("Filigranes SVG [detect/remove, défaut detect] : ").strip().lower()
            or "detect"
        )
        if args.watermarks not in {"detect", "remove"}:
            raise SystemExit("Politique de filigrane invalide.")
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
    if args.pdf and args.output_format and args.output_format != "pdf":
        raise SystemExit("Utilisez soit --pdf, soit --format, pas les deux.")
    args.output_format = "pdf" if args.pdf else (args.output_format or "cbz")
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
    print(f"Format : {args.output_format}")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nOpération annulée.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nERREUR : {exc}", file=sys.stderr)
        return 1
