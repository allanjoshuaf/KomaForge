from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doctor import run_doctor
from .diagnostic_ui import localize_diagnostic
from .paths import default_output_root
from .source_packages import default_source_packages_dir
from .terminal_ui import ensure_utf8_stream


DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge-doctor",
        description="Vérifie localement KomaForge sans modifier la bibliothèque.",
    )
    parser.add_argument("--root", type=Path, default=default_output_root())
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument(
        "--sources-directory",
        type=Path,
        default=default_source_packages_dir(),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--language", choices=("fr", "en", "ru", "zh"), default="fr")
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stream(sys.stdout)
    ensure_utf8_stream(sys.stderr)
    args = build_parser().parse_args(argv)
    report = run_doctor(
        root=args.root,
        chrome=args.chrome,
        sources_directory=args.sources_directory,
    )
    payload = report.to_record()
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        labels = {
            "fr": {"pass": "OK", "warn": "AVERTISSEMENT", "fail": "ÉCHEC"},
            "en": {"pass": "OK", "warn": "WARNING", "fail": "FAILED"},
            "ru": {"pass": "ОК", "warn": "ПРЕДУПРЕЖДЕНИЕ", "fail": "ОШИБКА"},
            "zh": {"pass": "正常", "warn": "警告", "fail": "失败"},
        }[args.language]
        for check in report.checks:
            detail = f" | {check.detail}" if check.detail else ""
            print(f"[{labels[check.status]}] {check.id}: {localize_diagnostic(check.summary, args.language)}{detail}")
        summary = {"fr": "Diagnostic global", "en": "Overall diagnosis", "ru": "Общий результат", "zh": "总体诊断"}[args.language]
        print(f"{summary} : {labels[report.status]}")
    return 1 if report.status == "fail" else 0
