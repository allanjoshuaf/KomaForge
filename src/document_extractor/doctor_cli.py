from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doctor import run_doctor
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
        labels = {"pass": "OK", "warn": "AVERTISSEMENT", "fail": "ÉCHEC"}
        for check in report.checks:
            detail = f" | {check.detail}" if check.detail else ""
            print(f"[{labels[check.status]}] {check.id}: {check.summary}{detail}")
        print(f"Diagnostic global : {labels[report.status]}")
    return 1 if report.status == "fail" else 0
