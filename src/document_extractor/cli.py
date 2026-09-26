from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .formats import OUTPUT_FORMATS
from .paths import default_output_dir, default_output_root, default_profile_dir
from .terminal_ui import (
    SUPPORTED_LANGUAGES,
    TerminalUI,
    choose_language,
    normalize_language,
    tr,
)


DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

PARSER_TEXT = {
    "fr": {
        "description": "Archive une publication web autorisée en CBZ, CBR, PDF, EPUB ou images.",
        "url": "URL de la publication. Sans URL, ouvre le menu interactif.",
        "language": "Langue de l’interface : fr, en, ru ou zh",
        "selector": "Sélecteur CSS des images (facultatif)", "expected": "Nombre de pages attendu",
        "output": "Dossier de sortie", "inspect": "Analyse sans rien télécharger",
        "scope": "Portée : auto, document courant ou œuvre complète", "chapters": "Parties : all ou 1-3,5",
        "reading_selector": "Contrôle du mode lecture", "reading_value": "Valeur du mode lecture",
        "allow_host": "Domaine de ressources supplémentaire", "ready_selector": "Élément indiquant que la page est prête",
        "wait": "Attendre une connexion manuelle", "profile": "Dossier du profil Chrome", "chrome": "Chemin de Chrome",
        "format": "Sortie : original, cbz, cbr, pdf, epub ou images", "pdf": "Alias de --format pdf",
        "recover": "Réparer explicitement un arbre PDF détaché autorisé", "retries": "Nouvelles tentatives réseau",
        "workers": "Téléchargements simultanés (défaut : 6)", "max_image": "Taille maximale d’une image en Mo",
        "watermarks": "SVG : remove retire les textes connus; detect ne modifie rien",
        "watermark_text": "Texte SVG exact à retirer; option répétable",
    },
    "en": {
        "description": "Archive an authorized web publication as CBZ, CBR, PDF, EPUB, or images.",
        "url": "Publication URL. Without one, opens the interactive menu.", "language": "Interface language: fr, en, ru, or zh",
        "selector": "Optional image CSS selector", "expected": "Expected page count", "output": "Output folder",
        "inspect": "Inspect without downloading", "scope": "Scope: automatic, current document, or complete work",
        "chapters": "Parts: all or 1-3,5", "reading_selector": "Reading-mode control", "reading_value": "Reading-mode value",
        "allow_host": "Additional resource domain", "ready_selector": "Element indicating that the page is ready",
        "wait": "Wait for a manual sign-in", "profile": "Chrome profile folder", "chrome": "Chrome executable path",
        "format": "Output: original, cbz, cbr, pdf, epub, or images", "pdf": "Alias for --format pdf",
        "recover": "Explicitly repair an authorized detached PDF tree", "retries": "Network retries",
        "workers": "Concurrent downloads (default: 6)", "max_image": "Maximum image size in MB",
        "watermarks": "SVG: remove known text; detect leaves content unchanged",
        "watermark_text": "Exact SVG text to remove; may be repeated",
    },
    "ru": {
        "description": "Архивирует разрешённую веб-публикацию в CBZ, CBR, PDF, EPUB или изображения.",
        "url": "URL публикации. Без URL откроется интерактивное меню.", "language": "Язык интерфейса: fr, en, ru или zh",
        "selector": "CSS-селектор изображений", "expected": "Ожидаемое число страниц", "output": "Папка вывода",
        "inspect": "Проверить без загрузки", "scope": "Область: авто, документ или всё произведение",
        "chapters": "Части: all или 1-3,5", "reading_selector": "Элемент режима чтения", "reading_value": "Значение режима чтения",
        "allow_host": "Дополнительный домен ресурсов", "ready_selector": "Элемент готовности страницы",
        "wait": "Ожидать ручной вход", "profile": "Папка профиля Chrome", "chrome": "Путь к Chrome",
        "format": "Формат: original, cbz, cbr, pdf, epub или images", "pdf": "Псевдоним --format pdf",
        "recover": "Восстановить разрешённое дерево PDF", "retries": "Сетевые повторы",
        "workers": "Параллельные загрузки (по умолчанию 6)", "max_image": "Максимальный размер изображения в МБ",
        "watermarks": "SVG: remove удаляет текст; detect ничего не меняет",
        "watermark_text": "Точный текст SVG для удаления",
    },
    "zh": {
        "description": "将获准的网页出版物归档为 CBZ、CBR、PDF、EPUB 或图片。",
        "url": "出版物 URL；省略时打开交互菜单。", "language": "界面语言：fr、en、ru 或 zh",
        "selector": "图片 CSS 选择器", "expected": "预计页数", "output": "输出目录", "inspect": "仅检查，不下载",
        "scope": "范围：自动、当前文档或完整作品", "chapters": "部分：all 或 1-3,5",
        "reading_selector": "阅读模式控件", "reading_value": "阅读模式值", "allow_host": "额外资源域名",
        "ready_selector": "页面就绪元素", "wait": "等待手动登录", "profile": "Chrome 配置目录", "chrome": "Chrome 路径",
        "format": "格式：original、cbz、cbr、pdf、epub 或 images", "pdf": "--format pdf 的别名",
        "recover": "修复获准的分离 PDF 页面树", "retries": "网络重试次数", "workers": "并行下载数（默认 6）",
        "max_image": "图片最大大小（MB）", "watermarks": "SVG：remove 删除文本；detect 不修改",
        "watermark_text": "要删除的精确 SVG 文本",
    },
}


def _preparse_language(argv: list[str] | None) -> str:
    values = list(sys.argv[1:] if argv is None else argv)
    for index, value in enumerate(values):
        if value in {"--language", "--lang"} and index + 1 < len(values):
            return normalize_language(values[index + 1])
        if value.startswith(("--language=", "--lang=")):
            return normalize_language(value.split("=", 1)[1])
    return normalize_language(os.environ.get("KOMAFORGE_LANG"), "fr")


def build_parser(language: str = "fr") -> argparse.ArgumentParser:
    language = normalize_language(language)
    h = PARSER_TEXT[language]
    parser = argparse.ArgumentParser(prog="komaforge", description=h["description"])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--language", "--lang", choices=SUPPORTED_LANGUAGES, default=language, help=h["language"])
    parser.add_argument("url", nargs="?", help=h["url"])
    parser.add_argument("--selector", help=h["selector"])
    parser.add_argument("--expected", type=int, help=h["expected"])
    parser.add_argument("--output", type=Path, help=h["output"])
    parser.add_argument("--inspect", action="store_true", help=h["inspect"])
    parser.add_argument("--scope", choices=("auto", "document", "work"), default="auto", help=h["scope"])
    parser.add_argument("--chapters", default="all", help=h["chapters"])
    parser.add_argument("--reading-mode-selector", help=h["reading_selector"])
    parser.add_argument("--reading-mode-value", help=h["reading_value"])
    parser.add_argument("--allow-host", action="append", default=[], help=h["allow_host"])
    parser.add_argument("--ready-selector", help=h["ready_selector"])
    parser.add_argument("--wait-for-user", action="store_true", help=h["wait"])
    parser.add_argument("--profile-dir", type=Path, help=h["profile"])
    parser.add_argument("--chrome", default=DEFAULT_CHROME, help=h["chrome"])
    parser.add_argument("--format", choices=OUTPUT_FORMATS, dest="output_format", help=h["format"])
    parser.add_argument("--pdf", action="store_true", help=h["pdf"])
    parser.add_argument("--recover-detached-pdf", action="store_true", help=h["recover"])
    parser.add_argument("--retries", type=int, default=3, help=h["retries"])
    parser.add_argument("--workers", type=int, choices=range(1, 13), default=6, metavar="1-12", help=h["workers"])
    parser.add_argument("--max-image-mb", type=int, default=50, help=h["max_image"])
    parser.add_argument("--watermarks", choices=("detect", "remove"), default="remove", help=h["watermarks"])
    parser.add_argument("--watermark-text", action="append", default=[], help=h["watermark_text"])
    parser.set_defaults(interactive=False)
    return parser


def ask_yes_no(prompt: str, language: str = "fr", default: bool = False) -> bool:
    suffixes = {
        "fr": "O/n" if default else "o/N", "en": "Y/n" if default else "y/N",
        "ru": "Д/н" if default else "д/Н", "zh": "是/否" if default else "是/否（默认否）",
    }
    answer = input(f"{prompt} [{suffixes[language]}] › ").strip().casefold()
    if not answer:
        return default
    yes = {
        "fr": {"o", "oui", "y", "yes"}, "en": {"y", "yes"},
        "ru": {"д", "да", "y", "yes"}, "zh": {"是", "好", "y", "yes", "1"},
    }
    return answer in yes[language]


def interactive_setup(args: argparse.Namespace) -> argparse.Namespace:
    args.interactive = True
    args.language = choose_language(getattr(args, "language", "fr"))
    ui = TerminalUI(args.language)
    ui.header()
    ui.section(ui.text("menu_title"))
    ui.option(1, ui.text("menu_auto"), ui.text("menu_auto_hint"))
    ui.option(2, ui.text("menu_advanced"), ui.text("menu_advanced_hint"))
    ui.option(3, ui.text("menu_quit"))
    choice = ui.prompt(ui.text("choice"), "1") or "1"
    if choice == "3":
        raise SystemExit(0)
    if choice not in {"1", "2"}:
        raise SystemExit(ui.text("invalid_choice"))

    ui.section(ui.text("source_title"))
    args.url = ui.prompt(ui.text("url_prompt"))
    if not args.url:
        raise SystemExit(ui.text("url_missing"))

    ui.section(ui.text("output_title"))
    output_default = str(default_output_root())
    custom_output = ui.prompt(ui.text("output_prompt"), output_default)
    if custom_output:
        args.output = Path(custom_output).expanduser()

    ui.section(ui.text("format_title"))
    ui.option(1, ui.text("format_original"), ui.text("format_original_hint"))
    ui.option(2, "CBZ", ui.text("format_cbz_hint"))
    ui.option(3, "CBR", ui.text("format_cbr_hint"))
    ui.option(4, "PDF", ui.text("format_pdf_hint"))
    ui.option(5, "EPUB", ui.text("format_epub_hint"))
    ui.option(6, "Images", ui.text("format_images_hint"))
    format_choice = ui.prompt(ui.text("format_prompt"), "1") or "1"
    format_map = {"1": "original", "2": "cbz", "3": "cbr", "4": "pdf", "5": "epub", "6": "images"}
    if format_choice not in format_map:
        raise SystemExit(ui.text("format_invalid"))
    args.output_format = format_map[format_choice]
    args.wait_for_user = ask_yes_no(ui.text("manual_login"), args.language)

    if choice == "2":
        ui.section(ui.text("advanced_title"))
        args.scope = ui.prompt(ui.text("scope_prompt"), "auto").casefold() or "auto"
        if args.scope not in {"auto", "document", "work"}:
            raise SystemExit(ui.text("scope_invalid"))
        args.selector = ui.prompt(ui.text("selector_prompt"), "auto") or None
        if args.selector == "auto":
            args.selector = None
        raw_expected = ui.prompt(ui.text("expected_prompt"), "auto")
        if raw_expected and raw_expected != "auto":
            try:
                args.expected = int(raw_expected)
            except ValueError as exc:
                raise SystemExit(ui.text("expected_invalid")) from exc
            if args.expected <= 0:
                raise SystemExit(ui.text("expected_invalid"))
        args.reading_mode_selector = ui.prompt(ui.text("reading_selector_prompt"), "auto") or None
        if args.reading_mode_selector == "auto":
            args.reading_mode_selector = None
        if args.reading_mode_selector:
            args.reading_mode_value = ui.prompt(ui.text("reading_value_prompt"), "auto") or None
            if args.reading_mode_value == "auto":
                args.reading_mode_value = None
        args.watermarks = ui.prompt(ui.text("watermark_prompt"), "remove").casefold() or "remove"
        if args.watermarks not in {"detect", "remove"}:
            raise SystemExit(ui.text("watermark_invalid"))
        exact_texts = ui.prompt(ui.text("watermark_text_prompt"))
        if exact_texts:
            args.watermark_text.append(exact_texts)
    if args.scope != "document":
        args.chapters = "ask"
    return args


def validate_url(url: str, language: str = "fr") -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(tr(language, "invalid_url"))


def normalize_url_input(value: str, language: str = "fr") -> str:
    value = value.strip()
    markdown = re.fullmatch(r"\[(https?://[^\]]+)\]\((https?://[^)]+)\)", value)
    if markdown:
        label, target = markdown.groups()
        if label != target:
            raise SystemExit(tr(language, "markdown_mismatch"))
        return target
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    language = _preparse_language(argv)
    args = build_parser(language).parse_args(argv)
    args.language = normalize_language(args.language)
    if not args.url:
        if not sys.stdin.isatty():
            raise SystemExit(tr(args.language, "missing_url_cli"))
        args = interactive_setup(args)
    args.url = normalize_url_input(args.url, args.language)
    validate_url(args.url, args.language)
    if args.pdf and args.output_format and args.output_format != "pdf":
        raise SystemExit(tr(args.language, "pdf_conflict"))
    args.output_format = "pdf" if args.pdf else (args.output_format or "cbz")
    args.output_auto_named = args.output is None
    args.output = args.output.expanduser().resolve() if args.output else default_output_dir(args.url)
    args.output_root = args.output.parent if args.output_auto_named else args.output
    args.profile_dir = args.profile_dir.expanduser().resolve() if args.profile_dir else default_profile_dir()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from .engine import run

    ui = TerminalUI(args.language)
    if not args.interactive:
        ui.header()
    ui.section(ui.text("summary_title"))
    ui.key_value(ui.text("label_url"), args.url)
    if args.inspect:
        ui.key_value(ui.text("label_mode"), ui.text("inspect_mode"))
    elif args.output_auto_named:
        ui.key_value(ui.text("label_output"), f"{args.output_root}\\{ui.text('auto_title_placeholder')}")
        ui.key_value(ui.text("label_format"), args.output_format)
    else:
        ui.key_value(ui.text("label_output"), args.output)
        ui.key_value(ui.text("label_format"), args.output_format)
    print()
    try:
        return run(args)
    except KeyboardInterrupt:
        print(f"\n{ui.text('cancelled')}", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\n{ui.text('error')} : {exc}", file=sys.stderr)
        return 1
