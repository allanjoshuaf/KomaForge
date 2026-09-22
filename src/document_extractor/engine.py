from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .detection import (
    ExpectedCount,
    activate_reading_mode,
    detect_expected_count,
    discover_pages,
    normalize_selector_input,
)


PAGE_TIMEOUT_MS = 90_000
REQUEST_TIMEOUT_MS = 45_000


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_chrome(port: int, timeout_seconds: int = 60) -> dict:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(
        "Chrome n'a pas ouvert son interface de contrôle. "
        "Un autre Chrome utilise peut-être le même profil."
    ) from last_error


def host_is_allowed(image_url: str, allowed_hosts: set[str]) -> bool:
    hostname = (urlparse(image_url).hostname or "").lower()
    return any(
        hostname == allowed or hostname.endswith("." + allowed)
        for allowed in allowed_hosts
    )


def sniff_extension(data: bytes, content_type: str) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    lowered = content_type.lower()
    for marker, extension in (
        ("jpeg", ".jpg"), ("png", ".png"), ("webp", ".webp"),
        ("gif", ".gif"),
    ):
        if marker in lowered:
            return extension
    return None


def valid_existing_file(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            head = stream.read(16)
        return sniff_extension(head, "") == path.suffix.lower()
    except OSError:
        return False


def download_pages(
    context,
    pages: list[dict],
    images_dir: Path,
    source_url: str,
    allowed_hosts: set[str],
    retries: int,
    max_image_bytes: int,
) -> tuple[list[dict], list[int]]:
    results: list[dict] = []
    missing: list[int] = []
    for position, item in enumerate(pages, start=1):
        page_number = int(item.get("page") or position)
        image_url = item["url"]
        if not host_is_allowed(image_url, allowed_hosts):
            print(f"[BLOQUÉ] page {page_number}: domaine non autorisé")
            missing.append(page_number)
            continue

        existing = next(images_dir.glob(f"page-{page_number:04d}.*"), None)
        if existing and valid_existing_file(existing):
            print(f"[DÉJÀ PRÉSENTE] page {page_number}/{len(pages)}")
            results.append(
                {
                    **item,
                    "file": existing.name,
                    "status": "existing",
                    "sha256": hashlib.sha256(existing.read_bytes()).hexdigest(),
                }
            )
            continue

        final_result = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                response = context.request.get(
                    image_url,
                    headers={"Referer": source_url},
                    timeout=REQUEST_TIMEOUT_MS,
                    fail_on_status_code=False,
                )
                if not response.ok:
                    raise RuntimeError(f"HTTP {response.status}")
                content_length = int(response.headers.get("content-length", "0") or 0)
                if content_length > max_image_bytes:
                    raise RuntimeError(
                        f"image trop grande ({content_length / 1024 / 1024:.1f} Mo)"
                    )
                data = response.body()
                if len(data) > max_image_bytes:
                    raise RuntimeError(
                        f"image trop grande ({len(data) / 1024 / 1024:.1f} Mo)"
                    )
                extension = sniff_extension(data, response.headers.get("content-type", ""))
                if extension is None:
                    raise RuntimeError(
                        "contenu non reconnu comme image "
                        f"({response.headers.get('content-type', '') or 'sans type'})"
                    )

                filename = images_dir / f"page-{page_number:04d}{extension}"
                partial = filename.with_suffix(filename.suffix + ".part")
                partial.write_bytes(data)
                partial.replace(filename)
                final_result = {
                    **item,
                    "file": filename.name,
                    "status": "downloaded",
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                print(f"[OK] page {page_number}/{len(pages)} ({len(data) / 1024:.0f} Ko)")
                break
            except Exception as exc:
                print(f"[ESSAI {attempt}/{retries}] page {page_number}: {exc}")
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
        if final_result:
            results.append(final_result)
        else:
            missing.append(page_number)
    return results, missing


def create_pdf(files: list[Path], output_pdf: Path) -> bool:
    try:
        import img2pdf
    except ImportError:
        print("PDF ignoré : installez img2pdf avec `python -m pip install img2pdf`.")
        return False
    output_pdf.write_bytes(img2pdf.convert([str(path) for path in files]))
    print(f"PDF : {output_pdf}")
    return True


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args) -> int:
    selector = normalize_selector_input(args.selector)
    source_host = (urlparse(args.url).hostname or "").lower()
    allowed_hosts = {source_host, *(host.lower() for host in args.allow_host)}
    if not Path(args.chrome).is_file():
        raise RuntimeError(f"Chrome introuvable : {args.chrome}")
    output_dir: Path = args.output
    images_dir = output_dir / "images"
    manifest_path = output_dir / "pages.json"
    images_dir.mkdir(parents=True, exist_ok=True)
    port = find_free_port()

    temporary_profile = None
    if args.profile_dir:
        profile_dir = args.profile_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary_profile = tempfile.TemporaryDirectory(prefix="document-extractor-profile-")
        profile_dir = Path(temporary_profile.name)

    chrome = subprocess.Popen(
        [
            args.chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "about:blank",
        ]
    )
    browser = None
    try:
        wait_for_chrome(port)
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            print(f"Ouverture : {args.url}")
            page.goto(args.url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

            if args.wait_for_user:
                input(
                    "Effectuez la connexion ou la validation dans Chrome, "
                    "puis appuyez sur Entrée..."
                )
            if args.ready_selector:
                page.locator(args.ready_selector).first.wait_for(
                    state="visible", timeout=PAGE_TIMEOUT_MS
                )

            reading_mode = activate_reading_mode(
                page,
                args.reading_mode_selector,
                args.reading_mode_value,
                True,
            )
            if reading_mode:
                print(f"Mode de lecture : {reading_mode['action']}")

            expected_info = (
                ExpectedCount(args.expected, "option --expected", "élevée")
                if args.expected
                else detect_expected_count(page)
            )
            pages, selector_used = discover_pages(
                page,
                selector,
                expected_info.value if expected_info else None,
            )
            if expected_info is None:
                try:
                    indices = sorted(int(item["document_index"]) for item in pages)
                except (KeyError, TypeError, ValueError):
                    indices = []
                if indices in (
                    list(range(0, len(pages))),
                    list(range(1, len(pages) + 1)),
                ):
                    expected_info = ExpectedCount(
                        len(pages),
                        "séquence data-index continue",
                        "élevée",
                    )
            expected = expected_info.value if expected_info else None

            print(f"Détection : {selector_used}")
            print(f"Pages trouvées : {len(pages)}")
            if expected_info:
                print(f"Pages attendues : {expected_info.value} ({expected_info.source})")
                if len(pages) != expected and not args.allow_partial:
                    raise RuntimeError(
                        f"Détection incomplète : {len(pages)}/{expected}. "
                        "Corrigez --selector ou utilisez --allow-partial."
                    )

            discovered_hosts = sorted(
                {(urlparse(item["url"]).hostname or "").lower() for item in pages}
            )
            print("Domaines détectés :", ", ".join(discovered_hosts))

            results, missing = download_pages(
                context=context,
                pages=pages,
                images_dir=images_dir,
                source_url=page.url,
                allowed_hosts=allowed_hosts,
                retries=args.retries,
                max_image_bytes=args.max_image_mb * 1024 * 1024,
            )
            manifest = {
                "source_url": args.url,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reading_mode": reading_mode,
                "selector": selector_used,
                "expected": expected,
                "expected_source": expected_info.source if expected_info else None,
                "detected": len(pages),
                "saved": len(results),
                "missing": missing,
                "pages": results,
            }
            write_json(manifest_path, manifest)
            if missing:
                print(f"Extraction incomplète : {len(missing)} page(s) manquante(s).")
                print(f"Manifeste : {manifest_path}")
                return 2

            print(f"Images : {images_dir}")
            print(f"Manifeste : {manifest_path}")
            if args.pdf:
                ordered = [images_dir / item["file"] for item in results]
                create_pdf(ordered, output_dir / "document.pdf")
            return 0
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        try:
            chrome.terminate()
            chrome.wait(timeout=10)
        except Exception:
            pass
        if temporary_profile is not None:
            try:
                temporary_profile.cleanup()
            except Exception:
                pass
