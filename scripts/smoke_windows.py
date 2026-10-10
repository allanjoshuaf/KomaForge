"""Exercise the portable program against local, controlled document fixtures."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.mock_site import MockDocumentHandler, NETWORK_EPUB


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockDocumentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env["KOMAFORGE_PROFILE_DIR"] = str(output / "profile")
    env["KOMAFORGE_OUTPUT_ROOT"] = str(output / "library")
    try:
        cases = (
            ("cbz", "/document", "cbz", 0),
            ("epub", "/network-epub-reader", "original", 0),
            ("pdf", "/network-epub-reader", "pdf", 0),
            ("images", "/network-epub-reader", "images", 0),
            ("incomplete", "/network-epub-reader-incomplete", "original", 2),
        )
        for name, route, selected_format, expected in cases:
            destination = output / name
            result = subprocess.run([
                str(args.executable.resolve()), f"http://127.0.0.1:{server.server_port}{route}",
                "--format", selected_format, "--output", str(destination),
            ], env=env, capture_output=True, text=True, encoding="utf-8", timeout=240)
            if result.returncode != expected:
                raise AssertionError(result.stdout + result.stderr)
            manifest = json.loads((destination / "pages.json").read_text("utf-8"))
            if expected == 0:
                assert manifest["publication"]["status"] == "complete", manifest
            else:
                assert manifest["publication"]["status"] == "incomplete", manifest
                assert not (destination / "document.epub").exists()
            if name == "epub":
                assert (destination / "document.epub").read_bytes() == NETWORK_EPUB
            if name == "pdf":
                import pypdfium2 as pdfium
                with pdfium.PdfDocument(destination / "document.pdf") as document:
                    for index in range(2):
                        text = document[index].get_textpage().get_text_range()
                        assert f"Section {index + 1}" in text, text
                        assert "Contenu EPUB de test" in text, text
                        assert "following errors" not in text, text
            print(f"{name}: passed", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
