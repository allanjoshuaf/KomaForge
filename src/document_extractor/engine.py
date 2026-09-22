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
from .formats import create_selected_output, file_sha256, remove_validated_work_directory
from .providers import discover_provider
from .resources import detect_resource, is_page_resource, resource_from_url_value
from .svg_tools import inspect_svg, remove_exact_watermarks


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
    parsed = urlparse(image_url)
    if parsed.scheme == "data":
        return True
    hostname = (parsed.hostname or "").lower()
    return any(
        hostname == allowed or hostname.endswith("." + allowed)
        for allowed in allowed_hosts
    )


def sniff_extension(data: bytes, content_type: str) -> str | None:
    try:
        info = detect_resource(data, content_type)
    except ValueError:
        return None
    return info.extension if is_page_resource(info) else None


def valid_existing_file(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            head = stream.read(8192)
        return sniff_extension(head, "") == path.suffix.lower()
    except OSError:
        return False


def _replace_failed_page(context, page):
    replacement = context.new_page()
    try:
        page.close()
    except Exception:
        pass
    return replacement


def _http_origin_warmup_url(url: str) -> str | None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"http://{parsed.hostname}/"


def navigate_to_source(context, page, url: str, retries: int = 3):
    """Open the source and recover from a Chromium SSL false start.

    Some filtered Windows networks return ERR_SSL_PROTOCOL_ERROR for the first
    direct Chromium request while accepting the site's HTTP -> HTTPS redirect.
    The recovery request contains only the origin, never the document path or
    query, and it must land on HTTPS on the same host before the source URL is
    tried again.
    """

    attempts = max(1, retries)
    target = urlparse(url)
    warmup_url = _http_origin_warmup_url(url)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            return page
        except Exception as exc:
            last_error = exc
            print(f"[NAVIGATION {attempt}/{attempts}] {str(exc).splitlines()[0]}")

            if "ERR_SSL_PROTOCOL_ERROR" in str(exc) and warmup_url:
                page = _replace_failed_page(context, page)
                try:
                    print("Récupération SSL : initialisation sécurisée du domaine...")
                    page.goto(
                        warmup_url,
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT_MS,
                    )
                    landed = urlparse(page.url)
                    if (
                        landed.scheme != "https"
                        or landed.hostname != target.hostname
                    ):
                        raise RuntimeError(
                            "le domaine n'a pas redirigé vers le même hôte en HTTPS"
                        )
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT_MS,
                    )
                    print("Récupération SSL réussie.")
                    return page
                except Exception as recovery_error:
                    last_error = recovery_error
                    print(
                        "Récupération SSL échouée : "
                        f"{str(recovery_error).splitlines()[0]}"
                    )

            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
                page = _replace_failed_page(context, page)

    raise RuntimeError(
        f"Impossible d'ouvrir le document après {attempts} tentative(s)."
    ) from last_error


def download_pages(
    context,
    pages: list[dict],
    images_dir: Path,
    source_url: str,
    allowed_hosts: set[str],
    retries: int,
    max_image_bytes: int,
    watermark_policy: str,
    watermark_texts: list[str],
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
                embedded = resource_from_url_value(image_url)
                if embedded is not None:
                    data, content_type = embedded
                else:
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
                    content_type = response.headers.get("content-type", "")
                if len(data) > max_image_bytes:
                    raise RuntimeError(
                        f"image trop grande ({len(data) / 1024 / 1024:.1f} Mo)"
                    )
                resource = detect_resource(
                    data,
                    content_type,
                    image_url,
                    max_uncompressed_bytes=max_image_bytes,
                )
                if not is_page_resource(resource):
                    raise RuntimeError(
                        "contenu non reconnu comme image "
                        f"({content_type or resource.kind})"
                    )

                output_data = resource.data
                svg_report = None
                removed_watermarks: list[dict] = []
                if resource.kind == "svg":
                    svg_report = inspect_svg(output_data)
                    if watermark_policy == "remove":
                        output_data, removed_watermarks = remove_exact_watermarks(
                            output_data,
                            watermark_texts,
                        )
                        svg_report = {
                            "before": svg_report,
                            "after": inspect_svg(output_data),
                            "removed": removed_watermarks,
                        }

                filename = images_dir / f"page-{page_number:04d}{resource.extension}"
                partial = filename.with_suffix(filename.suffix + ".part")
                partial.write_bytes(output_data)
                partial.replace(filename)
                final_result = {
                    **item,
                    "file": filename.name,
                    "status": "downloaded",
                    "bytes": len(output_data),
                    "sha256": hashlib.sha256(output_data).hexdigest(),
                    "source_sha256": resource.source_sha256,
                    "resource_kind": resource.kind,
                    "normalized": resource.normalized,
                    "normalization": resource.normalization,
                }
                if resource.kind == "svg":
                    final_result["svg"] = svg_report
                    final_result["watermarks_removed"] = len(removed_watermarks)
                print(f"[OK] page {page_number}/{len(pages)} ({len(output_data) / 1024:.0f} Ko)")
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
    work_dir = output_dir / ".komaforge-work"
    images_dir = output_dir / "images" if args.output_format == "images" else work_dir / "images"
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
            page = navigate_to_source(context, page, args.url, args.retries)

            provider = None if selector else discover_provider(context, page, args.url)
            if provider:
                allowed_hosts.update(provider.allowed_hosts)
                print(f"Profil du site : {provider.name}")

            if args.wait_for_user:
                input(
                    "Effectuez la connexion ou la validation dans Chrome, "
                    "puis appuyez sur Entrée..."
                )
            if args.ready_selector:
                page.locator(args.ready_selector).first.wait_for(
                    state="visible", timeout=PAGE_TIMEOUT_MS
                )

            reading_mode = (
                {
                    "action": "aucun contrôle requis",
                    "source": f"profil {provider.name}",
                }
                if provider and not args.reading_mode_selector
                else activate_reading_mode(
                    page,
                    args.reading_mode_selector,
                    args.reading_mode_value,
                    True,
                )
            )
            if reading_mode:
                print(f"Mode de lecture : {reading_mode['action']}")

            expected_info = (
                ExpectedCount(args.expected, "option --expected", "élevée")
                if args.expected
                else provider.expected if provider
                else detect_expected_count(page)
            )
            if provider:
                pages, selector_used = provider.pages, f"profil:{provider.name}"
            else:
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
                watermark_policy=args.watermarks,
                watermark_texts=args.watermark_text,
            )
            removed_total = sum(
                int(item.get("watermarks_removed") or 0) for item in results
            )
            manifest = {
                "source_url": args.url,
                "provider": provider.name if provider else None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reading_mode": reading_mode,
                "selector": selector_used,
                "expected": expected,
                "expected_source": expected_info.source if expected_info else None,
                "detected": len(pages),
                "saved": len(results),
                "missing": missing,
                "output_format": args.output_format,
                "quality": (
                    "SVG source preserved except exact watermark text; no resize"
                    if removed_total
                    else "original page bytes preserved; no resize"
                ),
                "watermark_policy": args.watermarks,
                "watermark_texts": args.watermark_text,
                "watermarks_removed": removed_total,
                "pages": results,
            }
            write_json(manifest_path, manifest)
            if missing:
                print(f"Extraction incomplète : {len(missing)} page(s) manquante(s).")
                print(f"Manifeste : {manifest_path}")
                return 2

            ordered = [images_dir / item["file"] for item in results]
            artifact = create_selected_output(
                args.output_format,
                ordered,
                output_dir,
                output_dir.name,
                chrome_executable=Path(args.chrome),
            )
            manifest["artifact"] = {
                "path": artifact.name if artifact.parent == output_dir else str(artifact),
                "sha256": file_sha256(artifact) if artifact.is_file() else None,
            }
            write_json(manifest_path, manifest)
            if args.output_format != "images":
                remove_validated_work_directory(work_dir, output_dir)
            print(f"Résultat : {artifact}")
            print(f"Manifeste : {manifest_path}")
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
