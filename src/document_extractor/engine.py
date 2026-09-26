from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .detection import (
    BLOB_CAPTURE_INIT_SCRIPT,
    ExpectedCount,
    access_interstitial_state,
    activate_reader_gate,
    activate_reading_mode,
    discover_chapters,
    discover_linked_reader,
    discover_manga_up_catalog,
    discover_selectable_parts,
    detect_expected_count,
    dismiss_cookie_consent,
    discover_pages,
    hydrate_lazy_content,
    is_ebooks_product_url,
    looks_like_chapter_url,
    normalize_selector_input,
    select_chapters,
    wait_for_access_interstitial,
    wait_for_reader_readiness,
)
from .formats import (
    create_pdf_from_epub_bytes,
    create_selected_output,
    file_sha256,
    inspect_epub,
    remove_validated_work_directory,
    render_pdf_bytes_to_images,
)
from .paths import (
    choose_title_output_dir,
    ensure_output_dir_is_compatible,
    publication_folder_title,
    safe_slug,
)
from .providers import discover_provider
from .resources import detect_resource, is_page_resource, resource_from_url_value
from .svg_tools import inspect_svg, remove_exact_watermarks
from .terminal_ui import rt


PAGE_TIMEOUT_MS = 90_000
REQUEST_TIMEOUT_MS = 45_000
PDF_REQUEST_TIMEOUT_MS = 180_000
PDF_RANGE_TIMEOUT_MS = 60_000
PDF_RANGE_CHUNK_BYTES = 4 * 1024 * 1024
PDF_BODY_REUSE_MAX_BYTES = 8 * 1024 * 1024


def cleanup_temporary_profile(
    temporary_profile: tempfile.TemporaryDirectory,
    profile_dir: Path,
    attempts: int = 8,
) -> bool:
    """Supprime un profil Chrome temporaire malgré les verrous Windows brefs."""
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            temporary_profile.cleanup()
            return not profile_dir.exists()
        except OSError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    try:
        shutil.rmtree(profile_dir)
        return True
    except OSError as exc:
        last_error = exc
    print(
        "[TEMP] Profil Chrome non supprimé après fermeture : "
        f"{profile_dir} ({last_error})"
    )
    return False


@dataclass(frozen=True)
class ChapterTask:
    index: int
    number: str
    title: str
    source_url: str
    pages: list[dict] | None = None
    expected: ExpectedCount | None = None
    kind: str = "chapter"
    control_selector: str | None = None
    control_value: str | None = None


def _complete_access_check(page, args) -> dict:
    initial = access_interstitial_state(page)
    if (
        initial["active"]
        and getattr(args, "interactive", False)
        and not args.wait_for_user
    ):
        input(
            "Vérification du site détectée dans Chrome. Terminez-la si le site "
            "demande une action, puis appuyez sur Entrée..."
        )
    return wait_for_access_interstitial(page)


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
    if parsed.scheme in {"data", "browser-blob"}:
        return True
    hostname = (parsed.hostname or "").lower()
    return any(
        hostname == allowed or hostname.endswith("." + allowed)
        for allowed in allowed_hosts
    )


def trusted_selected_resource_hosts(
    pages: list[dict],
    source_url: str,
    already_allowed: set[str],
) -> dict[str, int]:
    """Autorise seulement les CDN HTTPS répétés dans le groupe de pages retenu."""
    source_host = (urlparse(source_url).hostname or "").lower()
    hosts: Counter[str] = Counter()
    remote_count = 0
    for item in pages:
        parsed = urlparse(str(item.get("url") or ""))
        if parsed.scheme == "data":
            continue
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            continue
        remote_count += 1
        hosts[parsed.hostname.lower()] += 1

    trusted: dict[str, int] = {}
    for host, count in hosts.items():
        if host == source_host or host_is_allowed(f"https://{host}/", already_allowed):
            continue
        # Un logo ou une publicité isolée ne doit jamais agrandir la liste blanche.
        # Plusieurs CDN de pages restent possibles, à condition que chacun représente
        # une part significative du groupe finalement sélectionné.
        if count >= 3 and remote_count and count / remote_count >= 0.10:
            trusted[host] = count
    return trusted


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
    workers: int = 6,
) -> tuple[list[dict], list[int]]:
    results: list[dict] = []
    missing: list[int] = []
    pending: list[tuple[int, dict, int, str]] = []
    resume_path = images_dir / ".komaforge-resume.json"
    resume_pages: dict[str, dict] = {}
    try:
        resume_payload = json.loads(resume_path.read_text(encoding="utf-8"))
        if isinstance(resume_payload, dict) and isinstance(
            resume_payload.get("pages"), dict
        ):
            resume_pages = resume_payload["pages"]
    except (OSError, ValueError, TypeError):
        resume_pages = {}

    def remember(result: dict) -> None:
        page_key = str(int(result.get("page") or 0))
        resume_pages[page_key] = {
            "url": result.get("url"),
            "file": result.get("file"),
            "sha256": result.get("sha256"),
        }
        partial = resume_path.with_suffix(resume_path.suffix + ".part")
        partial.write_text(
            json.dumps({"version": 1, "pages": resume_pages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        partial.replace(resume_path)

    def finalize(
        item: dict,
        page_number: int,
        image_url: str,
        data: bytes,
        content_type: str,
    ) -> dict:
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
        for stale in images_dir.glob(f"page-{page_number:04d}.*"):
            if stale != filename and stale.name != partial.name:
                stale.unlink(missing_ok=True)
        public_item = {
            key: value for key, value in item.items() if not key.startswith("_")
        }
        result = {
            **public_item,
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
            result["svg"] = svg_report
            result["watermarks_removed"] = len(removed_watermarks)
        return result

    for position, item in enumerate(pages, start=1):
        page_number = int(item.get("page") or position)
        image_url = item["url"]
        if not item.get("_embedded_data") and not host_is_allowed(
            image_url, allowed_hosts
        ):
            print(f"[BLOQUÉ] page {page_number}: domaine non autorisé")
            missing.append(page_number)
            continue

        existing = next(
            (
                path
                for path in images_dir.glob(f"page-{page_number:04d}.*")
                if not path.name.endswith(".part")
            ),
            None,
        )
        resume_entry = resume_pages.get(str(page_number), {})
        if not isinstance(resume_entry, dict):
            resume_entry = {}
        existing_hash = file_sha256(existing) if existing and valid_existing_file(existing) else None
        reusable = bool(
            existing
            and existing_hash
            and resume_entry.get("url") == image_url
            and resume_entry.get("file") == existing.name
            and resume_entry.get("sha256") == existing_hash
        )
        if reusable:
            existing_data = existing.read_bytes()
            existing_result = {
                **item,
                "file": existing.name,
                "status": "existing",
                "bytes": len(existing_data),
            }
            if existing.suffix.lower() == ".svg":
                before = inspect_svg(existing_data)
                removed_watermarks: list[dict] = []
                if watermark_policy == "remove":
                    cleaned, removed_watermarks = remove_exact_watermarks(
                        existing_data,
                        watermark_texts,
                    )
                    if cleaned != existing_data:
                        partial = existing.with_suffix(existing.suffix + ".part")
                        partial.write_bytes(cleaned)
                        partial.replace(existing)
                        existing_data = cleaned
                        existing_result["status"] = "cleaned-existing"
                existing_result["svg"] = {
                    "before": before,
                    "after": inspect_svg(existing_data),
                    "removed": removed_watermarks,
                }
                existing_result["watermarks_removed"] = len(removed_watermarks)
            existing_result["bytes"] = len(existing_data)
            existing_result["sha256"] = hashlib.sha256(existing_data).hexdigest()
            remember(existing_result)
            print(
                f"[DÉJÀ PRÉSENTE] page {page_number}/{len(pages)} "
                f"({existing_result['status']})"
            )
            results.append(existing_result)
            continue
        pending.append((position, item, page_number, image_url))

    if not pending:
        return sorted(results, key=lambda item: int(item.get("page") or 0)), missing

    cookies = []
    user_agent = "Mozilla/5.0 KomaForge/0.3"
    if context is not None:
        try:
            cookies = context.cookies()
        except Exception:
            cookies = []
        try:
            live_pages = [page for page in context.pages if not page.is_closed()]
            if live_pages:
                user_agent = live_pages[-1].evaluate("navigator.userAgent")
        except Exception:
            pass

    def cookie_header(target_url: str) -> str:
        parsed = urlparse(target_url)
        target_host = (parsed.hostname or "").lower()
        target_path = parsed.path or "/"
        values = []
        now = time.time()
        for cookie in cookies:
            domain = str(cookie.get("domain") or "").lstrip(".").lower()
            path = str(cookie.get("path") or "/")
            expires = float(cookie.get("expires") or -1)
            if domain and not (
                target_host == domain or target_host.endswith("." + domain)
            ):
                continue
            if not target_path.startswith(path):
                continue
            if cookie.get("secure") and parsed.scheme != "https":
                continue
            if expires > 0 and expires < now:
                continue
            values.append(f"{cookie['name']}={cookie['value']}")
        return "; ".join(values)

    class AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not host_is_allowed(newurl, allowed_hosts):
                raise RuntimeError("redirection vers un domaine non autorisé")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(AllowedRedirectHandler())

    def direct_download(task: tuple[int, dict, int, str]) -> tuple[int, dict]:
        position, item, page_number, image_url = task
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                captured = item.get("_embedded_data")
                if isinstance(captured, bytes):
                    data = captured
                    content_type = str(
                        item.get("_embedded_content_type") or ""
                    )
                else:
                    embedded = resource_from_url_value(image_url)
                    if embedded is not None:
                        data, content_type = embedded
                    else:
                        headers = {
                            "Referer": source_url,
                            "User-Agent": user_agent,
                            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                            "Accept-Encoding": "identity",
                        }
                        cookie = cookie_header(image_url)
                        if cookie:
                            headers["Cookie"] = cookie
                        request = urllib.request.Request(image_url, headers=headers)
                        with opener.open(request, timeout=REQUEST_TIMEOUT_MS / 1000) as response:
                            final_url = response.geturl()
                            if not host_is_allowed(final_url, allowed_hosts):
                                raise RuntimeError(
                                    "redirection vers un domaine non autorisé"
                                )
                            content_length = int(
                                response.headers.get("content-length", "0") or 0
                            )
                            if content_length > max_image_bytes:
                                raise RuntimeError(
                                    "image trop grande "
                                    f"({content_length / 1024 / 1024:.1f} Mo)"
                                )
                            data = response.read(max_image_bytes + 1)
                            content_type = response.headers.get("content-type", "")
                return position, finalize(
                    item, page_number, image_url, data, content_type
                )
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError(str(last_error or "échec du téléchargement"))

    worker_count = max(1, min(int(workers), 12, len(pending)))
    print(
        f"Téléchargement parallèle : {worker_count} connexion(s), "
        f"{len(pending)} ressource(s)"
    )
    fallback: list[tuple[int, dict, int, str]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(direct_download, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                _position, result = future.result()
                results.append(result)
                remember(result)
                print(
                    f"[OK] page {task[2]}/{len(pages)} "
                    f"({result['bytes'] / 1024:.0f} Ko)"
                )
            except Exception:
                fallback.append(task)

    if fallback and context is not None:
        print(
            f"Repli navigateur : {len(fallback)} ressource(s) refusée(s) "
            "en téléchargement direct"
        )
    for _position, item, page_number, image_url in fallback:
        final_result = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                if context is None:
                    raise RuntimeError("contexte navigateur indisponible")
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
                final_result = finalize(
                    item,
                    page_number,
                    image_url,
                    response.body(),
                    response.headers.get("content-type", ""),
                )
                print(
                    f"[OK] page {page_number}/{len(pages)} "
                    f"({final_result['bytes'] / 1024:.0f} Ko, navigateur)"
                )
                break
            except Exception as exc:
                print(f"[ESSAI {attempt}/{retries}] page {page_number}: {exc}")
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
        if final_result:
            results.append(final_result)
            remember(final_result)
        else:
            missing.append(page_number)

    results.sort(key=lambda item: int(item.get("page") or 0))
    missing.sort()
    return results, missing


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _expected_from_continuous_indices(pages: list[dict]) -> ExpectedCount | None:
    try:
        indices = sorted(int(item["document_index"]) for item in pages)
    except (KeyError, TypeError, ValueError):
        return None
    if indices in (
        list(range(0, len(pages))),
        list(range(1, len(pages) + 1)),
    ):
        return ExpectedCount(
            len(pages),
            "séquence data-index continue",
            "élevée",
        )
    return None


def _artifact_manifest_path(artifact: Path, output_dir: Path) -> str:
    try:
        return artifact.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return str(artifact)


def _chapter_stem(chapter: ChapterTask) -> str:
    label = safe_slug(chapter.title)
    if label == "document":
        label = f"chapitre-{safe_slug(chapter.number)}"
    return safe_slug(f"{chapter.index:03d}-{label}")


def _part_label(kind: str, plural: bool = False, language: str = "fr") -> str:
    labels_by_language = {
        "fr": {"volume": ("Volume", "Volumes"), "book": ("Livre", "Livres"), "issue": ("Numéro", "Numéros"), "chapter": ("Chapitre", "Chapitres"), "document": ("Document", "Documents"), "part": ("Partie", "Parties")},
        "en": {"volume": ("Volume", "Volumes"), "book": ("Book", "Books"), "issue": ("Issue", "Issues"), "chapter": ("Chapter", "Chapters"), "document": ("Document", "Documents"), "part": ("Part", "Parts")},
        "ru": {"volume": ("Том", "Тома"), "book": ("Книга", "Книги"), "issue": ("Выпуск", "Выпуски"), "chapter": ("Глава", "Главы"), "document": ("Документ", "Документы"), "part": ("Часть", "Части")},
        "zh": {"volume": ("卷", "卷"), "book": ("书籍", "书籍"), "issue": ("期", "期"), "chapter": ("章节", "章节"), "document": ("文档", "文档"), "part": ("部分", "部分")},
    }
    labels = labels_by_language.get(language, labels_by_language["fr"])
    singular, plural_label = labels.get(kind, labels["part"])
    return plural_label if plural else singular


def _localized_runtime_value(value: str, language: str) -> str:
    translations = {
        "motif d'URL répété": {
            "en": "repeated URL pattern",
            "ru": "повторяющийся шаблон URL",
            "zh": "重复 URL 模式",
        },
        "séquence data-index continue": {
            "en": "continuous data-index sequence",
            "ru": "непрерывная последовательность data-index",
            "zh": "连续 data-index 序列",
        },
        "manifeste public Calaméo": {
            "en": "public Calaméo manifest",
            "ru": "публичный манифест Calaméo",
            "zh": "Calaméo 公共清单",
        },
        "aucun contrôle requis": {
            "en": "no control required",
            "ru": "дополнительное управление не требуется",
            "zh": "无需额外控制",
        },
        "ressources internes du navigateur": {
            "en": "internal browser resources",
            "ru": "внутренние ресурсы браузера",
            "zh": "浏览器内部资源",
        },
    }
    return translations.get(value, {}).get(language, value)


def _remember_browser_document(candidates: list[dict], response) -> None:
    """Mémorise une ressource documentaire chargée par le lecteur."""
    try:
        request = response.request
        content_type = response.headers.get("content-type", "").lower()
        disposition = response.headers.get("content-disposition", "").lower()
        if "application/pdf" in content_type or ".pdf" in disposition:
            document_format = "pdf"
        elif "application/epub+zip" in content_type or ".epub" in disposition:
            document_format = "epub"
        else:
            return
        if request.method != "GET":
            return
        if any(item.get("request") is request for item in candidates):
            return
        candidates.append(
            {
                "request": request,
                "response": response,
                "owner_page": request.frame.page,
                "document_format": document_format,
                "content_type": content_type,
                "content_disposition": disposition,
                "content_length": int(
                    response.headers.get("content-length", "0") or 0
                ),
                "accept_ranges": response.headers.get("accept-ranges", ""),
            }
        )
    except Exception:
        # Une réponse qui disparaît pendant une navigation ne doit jamais
        # interrompre l'extraction normale des images.
        return


def _remember_reader_metadata(candidates: list[dict], response) -> None:
    """Mémorise les réponses JSON susceptibles d'annoncer le total des pages."""
    try:
        request = response.request
        content_type = response.headers.get("content-type", "").lower()
        if request.method != "GET" or "json" not in content_type:
            return
        candidates.append(
            {
                "response": response,
                "owner_page": request.frame.page,
                "source": urlparse(response.url).path,
            }
        )
    except Exception:
        return


def _page_count_candidates(value, source: str, path: str = "root") -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        normalized = {
            "".join(character for character in str(key).lower() if character.isalnum()):
            (key, item)
            for key, item in value.items()
        }
        for normalized_key, (key, item) in normalized.items():
            child_path = f"{path}.{key}"
            if (
                normalized_key
                in {
                    "pagecount",
                    "totalpages",
                    "totalpagecount",
                    "numberofpages",
                    "numpages",
                    "pagetotal",
                }
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
                and 0 < int(item) <= 100_000
            ):
                score = 95
                if "total" in normalized_key or "numberof" in normalized_key:
                    score += 3
                if any(token in source.lower() for token in ("page", "label", "pdf")):
                    score += 4
                labels = normalized.get("labels")
                if labels and isinstance(labels[1], list) and len(labels[1]) == int(item):
                    score += 10
                found.append(
                    {
                        "value": int(item),
                        "source": f"métadonnées réseau: {source} ({child_path})",
                        "score": score,
                    }
                )
            found.extend(_page_count_candidates(item, source, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:1000]):
            found.extend(
                _page_count_candidates(item, source, f"{path}[{index}]")
            )
    return found


def _reader_publication_total(
    context, metadata_candidates: list[dict], page
) -> ExpectedCount | None:
    found: list[dict] = []
    for candidate in list(metadata_candidates):
        if candidate.get("owner_page") is not page:
            continue
        try:
            payload = candidate["response"].json()
        except Exception:
            try:
                request = candidate["response"].request
                headers = {
                    key: value
                    for key, value in request.all_headers().items()
                    if not key.startswith(":")
                    and key.lower()
                    not in {
                        "accept-encoding",
                        "connection",
                        "content-length",
                        "host",
                    }
                }
                replay = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_MS,
                )
                payload = replay.json()
            except Exception:
                continue
        found.extend(
            _page_count_candidates(payload, str(candidate.get("source") or "JSON"))
        )
    if not found:
        return None
    best = max(found, key=lambda item: (item["score"], item["value"]))
    return ExpectedCount(best["value"], best["source"], "élevée")


def _wait_for_publication_total(
    context,
    metadata_candidates: list[dict],
    page,
    timeout_ms: int = 15_000,
) -> ExpectedCount | None:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        total = _reader_publication_total(context, metadata_candidates, page)
        if total is not None:
            return total
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def _pdf_page_signature(page, pikepdf) -> tuple[str, tuple, tuple]:
    """Empreinte structurelle suffisante pour comparer deux objets /Page."""
    content = page.get("/Contents")
    streams = list(content) if isinstance(content, pikepdf.Array) else [content]
    digest = hashlib.sha256()
    for stream in streams:
        if stream is None:
            continue
        try:
            digest.update(stream.read_bytes())
        except Exception:
            try:
                digest.update(stream.read_raw_bytes())
            except Exception:
                digest.update(repr(stream).encode("utf-8", errors="replace"))
    media_box = tuple(float(value) for value in page.get("/MediaBox", []))
    crop_box = tuple(float(value) for value in page.get("/CropBox", []))
    return digest.hexdigest(), media_box, crop_box


def _flatten_pdf_page_tree(node, pikepdf, seen: set[tuple]) -> list:
    """Retourne les objets /Page d'un arbre dans l'ordre de son tableau /Kids."""
    try:
        reference = tuple(node.objgen)
    except Exception:
        reference = (id(node), 0)
    if reference in seen:
        raise ValueError("Cycle détecté dans une arborescence PDF /Pages.")
    seen.add(reference)

    object_type = str(node.get("/Type"))
    if object_type == "/Page":
        return [node]
    if object_type != "/Pages":
        raise ValueError(f"Enfant inattendu dans /Kids : {object_type}")

    pages = []
    for child in list(node.get("/Kids", [])):
        pages.extend(_flatten_pdf_page_tree(child, pikepdf, seen))
    return pages


def _pdf_page_tree_nodes(node, seen: set[tuple]) -> set[tuple]:
    """Inventorie les nœuds /Pages atteignables depuis l'arbre officiel."""
    try:
        reference = tuple(node.objgen)
    except Exception:
        reference = (id(node), 0)
    if reference in seen:
        return set()
    seen.add(reference)
    if str(node.get("/Type")) != "/Pages":
        return set()
    nodes = {reference}
    for child in list(node.get("/Kids", [])):
        if str(child.get("/Type")) == "/Pages":
            nodes.update(_pdf_page_tree_nodes(child, seen))
    return nodes


def inspect_detached_page_trees(data: bytes) -> dict:
    """Détecte, compte et valide les arbres /Pages détachés d'un PDF.

    La fonction reste strictement analytique : elle ne modifie pas le catalogue,
    ne rattache aucun objet et ne produit aucun nouveau document.
    """
    import pikepdf

    with pikepdf.Pdf.open(BytesIO(data)) as document:
        visible_pages = [page.obj for page in document.pages]
        page_count = len(visible_pages)
        if page_count < 1:
            raise ValueError("Le PDF ne contient aucune page officielle.")

        official_page_objects = {page.objgen for page in document.pages}
        official_tree_nodes = _pdf_page_tree_nodes(document.Root.Pages, set())
        detached_page_objects = 0
        detached_tree_counts: set[int] = set()
        detached_trees: list[dict] = []

        for obj in document.objects:
            try:
                object_type = str(obj.get("/Type"))
                if object_type == "/Page":
                    if obj.objgen not in official_page_objects:
                        detached_page_objects += 1
                    continue
                if object_type != "/Pages" or tuple(obj.objgen) in official_tree_nodes:
                    continue

                declared_count = int(obj.get("/Count", 0))
                if declared_count <= page_count:
                    continue
                detached_tree_counts.add(declared_count)
                detached_pages = _flatten_pdf_page_tree(obj, pikepdf, set())
                resolved_count = len(detached_pages)
                prefix_length = min(page_count, resolved_count)
                prefix_matches = sum(
                    _pdf_page_signature(visible_pages[index], pikepdf)
                    == _pdf_page_signature(detached_pages[index], pikepdf)
                    for index in range(prefix_length)
                )
                is_visible_prefix = (
                    prefix_length == page_count and prefix_matches == page_count
                )
                continuation = detached_pages[page_count:] if is_visible_prefix else []
                with_content = sum(
                    child.get("/Contents") is not None for child in continuation
                )
                with_resources = sum(
                    child.get("/Resources") is not None for child in continuation
                )
                detached_trees.append(
                    {
                        "object_reference": f"{obj.objgen[0]} {obj.objgen[1]} R",
                        "declared_count": declared_count,
                        "resolved_page_count": resolved_count,
                        "count_matches_resolved": declared_count == resolved_count,
                        "visible_prefix_matches": prefix_matches,
                        "visible_prefix_length": prefix_length,
                        "is_visible_prefix": is_visible_prefix,
                        "continuation_count": len(continuation),
                        "continuation_with_content": with_content,
                        "continuation_with_resources": with_resources,
                        "is_structurally_complete": (
                            declared_count == resolved_count
                            and is_visible_prefix
                            and with_content == len(continuation)
                            and with_resources == len(continuation)
                        ),
                    }
                )
            except Exception:
                continue

    return {
        "visible_page_count": page_count,
        "detached_page_objects": detached_page_objects,
        "detached_page_tree_counts": sorted(detached_tree_counts),
        "detached_ordered_page_trees": detached_trees,
    }


def recover_detached_page_tree(data: bytes, expected_count: int) -> tuple[bytes, dict]:
    """Reconstruit un PDF depuis un arbre détaché explicitement autorisé.

    La récupération n'est acceptée que si un unique arbre annonce exactement le
    nombre attendu, résout ce même nombre de pages, commence par toutes les pages
    officiellement visibles dans le même ordre et possède contenu et ressources
    pour toute sa continuation.
    """
    if expected_count < 1:
        raise ValueError("Le nombre de pages attendu doit être positif.")

    import pikepdf

    with pikepdf.Pdf.open(BytesIO(data)) as source:
        visible_pages = [page.obj for page in source.pages]
        visible_count = len(visible_pages)
        official_tree_nodes = _pdf_page_tree_nodes(source.Root.Pages, set())
        candidates: list[tuple[object, list]] = []

        for obj in source.objects:
            try:
                if (
                    str(obj.get("/Type")) != "/Pages"
                    or tuple(obj.objgen) in official_tree_nodes
                    or int(obj.get("/Count", 0)) != expected_count
                ):
                    continue
                pages = _flatten_pdf_page_tree(obj, pikepdf, set())
                if len(pages) != expected_count or visible_count > len(pages):
                    continue
                if any(
                    _pdf_page_signature(visible_pages[index], pikepdf)
                    != _pdf_page_signature(pages[index], pikepdf)
                    for index in range(visible_count)
                ):
                    continue
                continuation = pages[visible_count:]
                if any(page.get("/Contents") is None for page in continuation):
                    continue
                if any(page.get("/Resources") is None for page in continuation):
                    continue
                candidates.append((obj, pages))
            except Exception:
                continue

        if not candidates:
            raise RuntimeError(
                "Aucun arbre PDF détaché ne satisfait toutes les vérifications "
                "structurelles."
            )
        if len(candidates) > 1:
            raise RuntimeError(
                "Plusieurs arbres PDF détachés valides ont été trouvés; "
                "la récupération est ambiguë."
            )

        tree, pages = candidates[0]
        recovered = pikepdf.Pdf.new()
        for page in pages:
            recovered.pages.append(pikepdf.Page(page))
        output = BytesIO()
        recovered.save(output)
        recovered_data = output.getvalue()
        tree_reference = f"{tree.objgen[0]} {tree.objgen[1]} R"

    with pikepdf.Pdf.open(BytesIO(recovered_data)) as checked:
        recovered_count = len(checked.pages)
        if recovered_count != expected_count:
            raise RuntimeError(
                "Le PDF reconstruit a échoué à la validation : "
                f"{recovered_count}/{expected_count} pages."
            )

    return recovered_data, {
        "authorized": True,
        "tree_object_reference": tree_reference,
        "source_visible_page_count": visible_count,
        "recovered_page_count": recovered_count,
        "continuation_page_count": recovered_count - visible_count,
        "method": "ordered detached /Pages tree",
    }


def _fetch_pdf_in_ranges(context, request, headers: dict, total: int) -> bytes:
    """Télécharge un gros PDF par segments vérifiés dans la même session."""
    chunks: list[bytes] = []
    starts = list(range(0, total, PDF_RANGE_CHUNK_BYTES))
    for position, start in enumerate(starts, 1):
        end = min(start + PDF_RANGE_CHUNK_BYTES - 1, total - 1)
        ranged_headers = {**headers, "range": f"bytes={start}-{end}"}
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=ranged_headers,
                    timeout=PDF_RANGE_TIMEOUT_MS,
                )
                body = response.body()
                if response.status == 200 and start == 0 and len(body) == total:
                    print("Récupération PDF : le serveur a renvoyé le fichier complet")
                    return body
                if response.status != 206:
                    raise RuntimeError(
                        f"HTTP {response.status} au lieu de 206 pour les octets "
                        f"{start}-{end}"
                    )
                expected_size = end - start + 1
                if len(body) != expected_size:
                    raise RuntimeError(
                        f"segment {start}-{end} tronqué : "
                        f"{len(body)}/{expected_size} octets"
                    )
                chunks.append(body)
                print(
                    f"Récupération PDF : segment {position}/{len(starts)} "
                    f"({end + 1}/{total} octets)"
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise RuntimeError(
                        f"Échec du segment PDF {start}-{end} après deux "
                        f"tentatives : {last_error}"
                    ) from exc
        else:
            raise RuntimeError(str(last_error))
    data = b"".join(chunks)
    if len(data) != total:
        raise RuntimeError(
            f"PDF assemblé incomplet : {len(data)}/{total} octets."
        )
    return data


def _fetch_browser_pdf(context, candidate: dict) -> tuple[bytes, int, dict]:
    """Récupère le PDF observé, puis le rejoue seulement si nécessaire."""
    request = candidate["request"]
    data = b""
    content_type = str(candidate.get("content_type") or "").lower()
    content_length = int(candidate.get("content_length") or 0)
    observed_response = candidate.get("response")
    if (
        observed_response is not None
        and 0 < content_length <= PDF_BODY_REUSE_MAX_BYTES
    ):
        try:
            if not observed_response.ok:
                raise RuntimeError(
                    f"Ressource PDF inaccessible : HTTP {observed_response.status}"
                )
            data = observed_response.body()
            content_type = observed_response.headers.get(
                "content-type", content_type
            ).lower()
            if data:
                print("Ressource PDF : réponse déjà chargée par le navigateur")
        except Exception:
            data = b""

    headers = {
        key: value
        for key, value in request.all_headers().items()
        if not key.startswith(":")
        and key.lower()
        not in {"accept-encoding", "connection", "content-length", "host", "range"}
    }
    if (
        not data
        and content_length > PDF_BODY_REUSE_MAX_BYTES
        and str(candidate.get("accept_ranges") or "").lower() == "bytes"
    ):
        data = _fetch_pdf_in_ranges(context, request, headers, content_length)

    if not data:
        headers = {
            key: value
            for key, value in headers.items()
            if not key.startswith(":")
            and key.lower()
            not in {"accept-encoding", "connection", "content-length", "host"}
        }
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=PDF_REQUEST_TIMEOUT_MS,
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Ressource PDF inaccessible : HTTP {response.status}"
                    )
                data = response.body()
                content_type = response.headers.get(
                    "content-type", content_type
                ).lower()
                break
            except Exception as exc:
                last_error = exc
                print(f"Récupération PDF {attempt}/2 échouée : {exc}")
        if not data:
            raise RuntimeError(
                "La ressource PDF n'a pas pu être récupérée après deux "
                f"tentatives : {last_error}"
            )
    if "application/pdf" not in content_type and not data.startswith(b"%PDF-"):
        raise RuntimeError(
            "La ressource documentaire détectée n'est pas un PDF valide."
        )
    if not data.startswith(b"%PDF-"):
        raise RuntimeError("Le lecteur a renvoyé un PDF vide ou invalide.")

    try:
        import pikepdf
    except ImportError as exc:
        raise RuntimeError(
            "La ressource PDF a été trouvée, mais sa validation demande "
            "pikepdf : python -m pip install pikepdf"
        ) from exc
    try:
        diagnostics = inspect_detached_page_trees(data)
        page_count = diagnostics["visible_page_count"]
    except Exception as exc:
        raise RuntimeError(
            "La ressource PDF détectée ne peut pas être validée : "
            f"{exc}"
        ) from exc
    if page_count < 1:
        raise RuntimeError("La ressource PDF détectée ne contient aucune page.")
    return data, page_count, diagnostics


def _fetch_browser_epub(
    context,
    candidate: dict,
    language: str = "fr",
) -> tuple[bytes, dict]:
    """Récupère et valide l'EPUB observé dans la session réelle du lecteur."""
    request = candidate["request"]
    data = b""
    observed_response = candidate.get("response")
    content_length = int(candidate.get("content_length") or 0)
    if observed_response is not None and 0 < content_length <= PDF_BODY_REUSE_MAX_BYTES:
        try:
            if not observed_response.ok:
                raise RuntimeError(
                    f"Ressource EPUB inaccessible : HTTP {observed_response.status}"
                )
            data = observed_response.body()
            if data:
                print(rt(language, "epub_loaded"))
        except Exception:
            data = b""

    if not data:
        headers = {
            key: value
            for key, value in request.all_headers().items()
            if not key.startswith(":")
            and key.lower()
            not in {"accept-encoding", "connection", "content-length", "host", "range"}
        }
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=PDF_REQUEST_TIMEOUT_MS,
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Ressource EPUB inaccessible : HTTP {response.status}"
                    )
                data = response.body()
                break
            except Exception as exc:
                last_error = exc
                print(f"Récupération EPUB {attempt}/2 échouée : {exc}")
        if not data:
            raise RuntimeError(
                "La ressource EPUB n'a pas pu être récupérée après deux "
                f"tentatives : {last_error}"
            )
    try:
        info = inspect_epub(data)
    except Exception as exc:
        raise RuntimeError(f"La ressource EPUB détectée est invalide : {exc}") from exc
    return data, info


def _direct_document_candidate(candidates: list[dict], page, output_format: str) -> dict | None:
    matching = [
        item
        for item in candidates
        if item.get("owner_page") is page
    ]
    if not matching:
        return None
    if output_format in {"pdf", "epub"}:
        native = [
            item for item in matching
            if item.get("document_format") == output_format
        ]
        if native:
            return native[-1]
    return matching[-1]


def resolve_part_selection(
    chapters: list[ChapterTask],
    expression: str,
    kind: str,
    default_expression: str = "1",
    language: str = "fr",
) -> list[ChapterTask]:
    if expression == "ask":
        noun = _part_label(kind, plural=True, language=language).lower()
        prompts = {
            "fr": "Sélection des {noun} [1, all ou 1-3,5; défaut {default}] : ",
            "en": "Select {noun} [1, all, or 1-3,5; default {default}]: ",
            "ru": "Выберите {noun} [1, all или 1-3,5; по умолчанию {default}]: ",
            "zh": "选择{noun} [1、all 或 1-3,5；默认 {default}]：",
        }
        expression = (
            input(
                prompts.get(language, prompts["fr"]).format(
                    noun=noun,
                    default=default_expression,
                )
            ).strip()
            or default_expression
        )
    return select_chapters(chapters, expression)


def _wait_for_selected_part(page, chapter: ChapterTask) -> None:
    if not chapter.control_selector or chapter.control_value is None:
        return
    control = page.locator(chapter.control_selector).first
    control.wait_for(state="visible", timeout=PAGE_TIMEOUT_MS)
    if control.input_value() != chapter.control_value:
        control.select_option(chapter.control_value)
    try:
        page.wait_for_function(
            r"""
            () => [...document.images].filter(image => {
                const text = [image.id, image.className, image.alt,
                    image.parentElement?.id, image.parentElement?.className]
                    .join(' ').toLowerCase();
                const source = image.currentSrc || image.src ||
                    image.dataset.src || image.dataset.lazySrc || '';
                return /(page|scan|chapter|chapitre|volume|manga|comic)/.test(text) &&
                    !/(logo|icon|avatar|advert|sponsor|thumbnail|loading)/.test(text) &&
                    Boolean(source);
            }).length >= 2
            """,
            timeout=15_000,
        )
    except Exception:
        # La détection complète qui suit reste l'autorité : ce court délai sert
        # seulement aux lecteurs qui peuplent leurs images après un changement.
        pass


def _ask_interactive_detached_recovery(
    args, pdf_diagnostics: dict, expected_count: int
) -> bool:
    """Demande l'accord seulement lorsqu'un arbre complet a été démontré."""
    if not getattr(args, "interactive", False) or args.inspect:
        return False
    candidates = [
        tree
        for tree in pdf_diagnostics.get("detached_ordered_page_trees", [])
        if tree.get("declared_count") == expected_count
        and tree.get("is_structurally_complete")
    ]
    if len(candidates) != 1:
        return False
    answer = input(
        "Arborescence PDF complète vérifiée. La reconstruire pour ce "
        "document que vous possédez ou êtes autorisé à tester ? [o/N] "
    ).strip().casefold()
    return answer in {"o", "oui", "y", "yes"}


def _use_direct_pdf(
    *,
    context,
    candidate: dict,
    chapter: ChapterTask,
    args,
    output_dir: Path,
    work_dir: Path,
    publication_is_work: bool,
    reading_mode: dict | None,
    reader_expected: ExpectedCount | None,
    metadata_candidates: list[dict],
    page,
) -> tuple[dict, bool]:
    language = getattr(args, "language", "fr")
    selected_output_format = (
        "pdf" if args.output_format in {"auto", "original"} else args.output_format
    )
    if args.output_format in {"auto", "original"}:
        print("Format original retenu : PDF")
    data, page_count, pdf_diagnostics = _fetch_browser_pdf(context, candidate)
    source_visible_page_count = page_count
    recovery: dict | None = None
    publication_expected = _wait_for_publication_total(
        context, metadata_candidates, page
    )
    authoritative_expected = (
        publication_expected
        if publication_expected and publication_expected.value >= page_count
        else ExpectedCount(page_count, "structure du PDF", "élevée")
    )
    incomplete = page_count < authoritative_expected.value
    recover_requested = args.recover_detached_pdf
    if incomplete and not recover_requested:
        recover_requested = _ask_interactive_detached_recovery(
            args, pdf_diagnostics, authoritative_expected.value
        )
    if incomplete and recover_requested and not args.inspect:
        try:
            data, recovery = recover_detached_page_tree(
                data, authoritative_expected.value
            )
        except Exception as exc:
            print(f"[RÉCUPÉRATION REFUSÉE] {exc}")
        else:
            page_count = recovery["recovered_page_count"]
            incomplete = page_count < authoritative_expected.value
            pdf_diagnostics["recovery"] = recovery
    missing_count = max(authoritative_expected.value - page_count, 0)
    size_mb = len(data) / (1024 * 1024)
    print("Détection : ressource PDF chargée par le navigateur")
    print(f"Ressource documentaire : {size_mb:.1f} Mo")
    print(f"Pages du PDF : {source_visible_page_count}")
    if reader_expected and reader_expected.value != page_count:
        print(
            "Pagination affichée par le lecteur : "
            f"{reader_expected.value} "
            f"({reader_expected.source})"
        )
    if recovery is not None and not incomplete:
        print(
            "[RÉCUPÉRÉ] Arborescence PDF détachée validée : "
            f"{page_count} pages, dont "
            f"{recovery['continuation_page_count']} dans la continuation."
        )
    elif incomplete:
        print(
            "[INCOMPLET] Publication : "
            f"{page_count}/{authoritative_expected.value} pages "
            f"({missing_count} manquante(s))"
        )
        ordered_trees = [
            tree
            for tree in pdf_diagnostics["detached_ordered_page_trees"]
            if tree["is_visible_prefix"]
        ]
        if ordered_trees:
            tree = max(ordered_trees, key=lambda item: item["declared_count"])
            print(
                "Diagnostic PDF : les "
                f"{tree['visible_prefix_matches']} pages visibles correspondent "
                "au préfixe d'une arborescence détachée ordonnée de "
                f"{tree['declared_count']} pages. Sa continuation contient "
                f"{tree['continuation_count']} objet(s) /Page, dont "
                f"{tree['continuation_with_content']} avec contenu et "
                f"{tree['continuation_with_resources']} avec ressources."
            )
        elif pdf_diagnostics["detached_page_tree_counts"]:
            print(
                "Diagnostic PDF : arborescence(s) de pages détachée(s) "
                "déclarant "
                f"{', '.join(map(str, pdf_diagnostics['detached_page_tree_counts']))} "
                "page(s); "
                "elles ne font pas partie du document lisible."
            )

    record = {
        "index": chapter.index,
        "number": chapter.number,
        "title": chapter.title,
        "kind": chapter.kind,
        "source_url": chapter.source_url,
        "output_format": selected_output_format,
        "reading_mode": reading_mode,
        "selector": "network:application/pdf",
        "expected": authoritative_expected.value,
        "expected_source": authoritative_expected.source,
        "reader_expected": reader_expected.value if reader_expected else None,
        "detected": page_count,
        "source_visible_page_count": source_visible_page_count,
        "recovered_from_detached_tree": recovery is not None and not incomplete,
        "resource_count": 1,
        "resource_unit": "pdf_document",
        "saved": 0,
        "missing": (
            [f"{page_count + 1}-{authoritative_expected.value}"]
            if incomplete
            else []
        ),
        "missing_count": missing_count,
        "watermarks_removed": 0,
        "quality": (
            "original page objects reassembled; no rasterization"
            if selected_output_format == "pdf" and recovery is not None and not incomplete
            else "original PDF bytes preserved; no re-encoding"
            if selected_output_format == "pdf"
            else f"PDF pages rasterized losslessly to PNG at 200 dpi for {selected_output_format}"
        ),
        "pdf_diagnostics": pdf_diagnostics,
    }
    if args.inspect:
        record["status"] = "incomplete" if incomplete else "inspected"
        return record, not incomplete

    if incomplete:
        record["status"] = "incomplete"
        print(
            "Aucun PDF sauvegardé : le lecteur n'a fourni qu'un aperçu "
            "incomplet."
        )
        return record, False

    if publication_is_work:
        artifact_dir = output_dir / (
            "volumes" if chapter.kind == "volume" else "chapters"
        )
        output_stem = _chapter_stem(chapter)
    else:
        artifact_dir = output_dir
        output_stem = getattr(args, "output_stem", "document")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if selected_output_format == "pdf":
        artifact = artifact_dir / f"{output_stem}.pdf"
        artifact.write_bytes(data)
    else:
        images_dir = (
            artifact_dir / output_stem
            if selected_output_format == "images" and publication_is_work
            else output_dir / "images"
            if selected_output_format == "images"
            else work_dir / output_stem / "images"
            if publication_is_work
            else work_dir / "images"
        )
        print(
            "Conversion demandée : rendu des pages PDF en PNG à 200 ppp "
            f"pour produire {selected_output_format.upper()}."
        )
        rendered = render_pdf_bytes_to_images(data, images_dir, dpi=200)
        artifact = create_selected_output(
            selected_output_format,
            rendered,
            artifact_dir,
            chapter.title,
            chrome_executable=Path(args.chrome),
            output_stem=output_stem,
        )
        record["resource_unit"] = "rendered_pdf_page"
        record["render_dpi"] = 200
    record["saved"] = page_count
    record["artifact"] = {
        "path": _artifact_manifest_path(artifact, output_dir),
        "sha256": file_sha256(artifact) if artifact.is_file() else None,
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }
    record["status"] = "complete"
    print(rt(language, "result", value=artifact))
    return record, not incomplete


def _use_direct_epub(
    *,
    context,
    candidate: dict,
    chapter: ChapterTask,
    args,
    output_dir: Path,
    work_dir: Path,
    publication_is_work: bool,
    reading_mode: dict | None,
) -> tuple[dict, bool]:
    language = getattr(args, "language", "fr")
    selected_output_format = (
        "epub" if args.output_format in {"auto", "original"} else args.output_format
    )
    if args.output_format in {"auto", "original"}:
        print("Format original retenu : EPUB")
    data, epub_info = _fetch_browser_epub(context, candidate, language)
    size_mb = len(data) / (1024 * 1024)
    spine_count = int(epub_info["spine_item_count"])
    referenced_count = int(epub_info.get("referenced_document_count") or 0)
    present_referenced = len(epub_info.get("present_referenced_documents") or [])
    missing_documents = list(epub_info.get("missing_referenced_documents") or [])
    incomplete = bool(missing_documents)
    detected_count = present_referenced if referenced_count else spine_count
    expected_count = referenced_count or spine_count
    print(rt(language, "epub_detection"))
    print(rt(language, "document_resource", size=size_mb))
    print(rt(language, "epub_sections", count=spine_count))
    if referenced_count:
        print(
            rt(
                language,
                "epub_toc",
                present=present_referenced,
                total=referenced_count,
            )
        )
    if incomplete:
        print(rt(language, "epub_incomplete", missing=len(missing_documents)))
        if epub_info.get("orphan_local_entries"):
            print(
                "Diagnostic EPUB : des entrées ZIP locales détachées existent "
                "et demandent une analyse supplémentaire."
            )
        else:
            print(rt(language, "epub_no_orphans"))
        print(
            rt(
                language,
                "extraction_refused",
                present=detected_count,
                total=expected_count,
                missing=len(missing_documents),
            )
        )

    record = {
        "index": chapter.index,
        "number": chapter.number,
        "title": chapter.title,
        "kind": chapter.kind,
        "source_url": chapter.source_url,
        "output_format": selected_output_format,
        "reading_mode": reading_mode,
        "selector": "network:application/epub+zip",
        "expected": expected_count,
        "expected_source": (
            "liens de la table des matières EPUB"
            if referenced_count
            else "spine EPUB"
        ),
        "detected": detected_count,
        "resource_count": 1,
        "resource_unit": "epub_document",
        "epub_spine_items": spine_count,
        "saved": 0,
        "missing": missing_documents,
        "missing_count": len(missing_documents),
        "watermarks_removed": 0,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "epub_diagnostics": {
            "entry_count": epub_info.get("entry_count"),
            "local_entry_count": epub_info.get("local_entry_count"),
            "referenced_document_count": referenced_count,
            "present_referenced_document_count": present_referenced,
            "missing_referenced_documents": missing_documents,
            "orphan_local_entries": epub_info.get("orphan_local_entries"),
            "trailing_bytes_after_eocd": epub_info.get("trailing_bytes_after_eocd"),
            "is_structurally_complete": not incomplete,
        },
    }
    if args.inspect:
        record["status"] = "incomplete" if incomplete else "inspected"
        record["quality"] = "original EPUB validated; no output written"
        return record, not incomplete

    if incomplete:
        record["status"] = "incomplete"
        record["quality"] = "incomplete EPUB rejected before output"
        print(
            "Aucun fichier de lecture sauvegardé : la ressource EPUB reçue "
            "ne couvre pas tous les documents annoncés par sa propre table "
            "des matières."
        )
        return record, False

    if publication_is_work:
        artifact_dir = output_dir / (
            "volumes" if chapter.kind == "volume" else "chapters"
        )
        output_stem = _chapter_stem(chapter)
    else:
        artifact_dir = output_dir
        output_stem = getattr(args, "output_stem", "document")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    page_count: int | None = None
    if selected_output_format == "epub":
        artifact = artifact_dir / f"{output_stem}.epub"
        artifact.write_bytes(data)
        record["quality"] = "original EPUB bytes preserved; no re-encoding"
        record["saved"] = spine_count
    else:
        converted_pdf = work_dir / output_stem / "source-rendered.pdf"
        converted_pdf.parent.mkdir(parents=True, exist_ok=True)
        print(
            "Conversion EPUB : impression des sections XHTML avec Chrome "
            "en conservant texte, images et mise en forme."
        )
        converted_pdf, conversion = create_pdf_from_epub_bytes(
            data,
            converted_pdf,
            Path(args.chrome),
        )
        page_count = int(conversion["page_count"])
        print(f"Pages produites après mise en pages EPUB : {page_count}")
        if selected_output_format == "pdf":
            artifact = artifact_dir / f"{output_stem}.pdf"
            converted_pdf.replace(artifact)
            record["quality"] = (
                "reflowable EPUB printed to vector/text PDF with Chrome"
            )
        else:
            images_dir = (
                artifact_dir / output_stem
                if selected_output_format == "images" and publication_is_work
                else output_dir / "images"
                if selected_output_format == "images"
                else work_dir / output_stem / "images"
            )
            rendered = render_pdf_bytes_to_images(
                converted_pdf.read_bytes(), images_dir, dpi=200
            )
            converted_pdf.unlink(missing_ok=True)
            if selected_output_format == "images":
                for empty_dir in (converted_pdf.parent, work_dir):
                    try:
                        empty_dir.rmdir()
                    except OSError:
                        pass
            artifact = create_selected_output(
                selected_output_format,
                rendered,
                artifact_dir,
                chapter.title,
                chrome_executable=Path(args.chrome),
                output_stem=output_stem,
            )
            record["resource_unit"] = "rendered_epub_page"
            record["render_dpi"] = 200
            record["quality"] = (
                "EPUB laid out with Chrome then rasterized losslessly to PNG "
                f"at 200 dpi for {selected_output_format}"
            )
        record["detected"] = page_count
        record["saved"] = page_count

    record["artifact"] = {
        "path": _artifact_manifest_path(artifact, output_dir),
        "sha256": file_sha256(artifact) if artifact.is_file() else None,
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }
    record["status"] = "complete"
    print(rt(language, "result", value=artifact))
    return record, True


def extract_chapter(
    *,
    context,
    page,
    chapter: ChapterTask,
    args,
    selector: str | None,
    allowed_hosts: set[str],
    output_dir: Path,
    work_dir: Path,
    publication_is_work: bool,
    provider_name: str | None,
    reuse_current_page: bool,
    document_candidates: list[dict],
    metadata_candidates: list[dict],
) -> tuple[object, dict, bool]:
    language = getattr(args, "language", "fr")
    print(
        "\n" + rt(
            language,
            "part_heading",
            label=_part_label(chapter.kind, language=language),
            index=chapter.index,
            title=chapter.title,
        )
    )
    if chapter.pages is None and not reuse_current_page:
        page = navigate_to_source(context, page, chapter.source_url, args.retries)

    interstitial = _complete_access_check(page, args)
    if not interstitial["passed"]:
        raise RuntimeError(
            "La vérification du site est toujours active. Relancez avec "
            "--wait-for-user et terminez-la dans Chrome avant de continuer."
        )
    if interstitial["encountered"]:
        print(rt(language, "access_check", seconds=interstitial["waited_ms"] / 1000))

    _wait_for_selected_part(page, chapter)

    consent = dismiss_cookie_consent(page)
    if consent:
        print(rt(language, "consent", value=consent["action"]))

    if args.ready_selector:
        page.locator(args.ready_selector).first.wait_for(
            state="visible",
            timeout=PAGE_TIMEOUT_MS,
        )

    reader_gate = activate_reader_gate(page)
    if reader_gate:
        print(rt(language, "reader_start", value=reader_gate["action"]))

    readiness = wait_for_reader_readiness(page)
    if readiness["waited_ms"]:
        print(rt(language, "reader_initialization", seconds=readiness["waited_ms"] / 1000))

    reading_mode = (
        {
            "action": "aucun contrôle requis",
            "source": f"profil {provider_name}",
        }
        if chapter.pages is not None and provider_name and not args.reading_mode_selector
        else activate_reading_mode(
            page,
            args.reading_mode_selector,
            args.reading_mode_value,
            True,
        )
    )
    if reading_mode:
        print(
            rt(
                language,
                "reading_mode",
                value=_localized_runtime_value(reading_mode["action"], language),
            )
        )

    early_expected_info = (
        ExpectedCount(args.expected, "option --expected", "élevée")
        if args.expected
        else chapter.expected
    )
    if chapter.pages is None:
        if early_expected_info is None:
            early_expected_info = detect_expected_count(page)
        provisional_hydration_single = (
            args.expected is None
            and early_expected_info is not None
            and early_expected_info.value == 1
            and early_expected_info.confidence != "élevée"
        )
        hydration = hydrate_lazy_content(
            page,
            None
            if provisional_hydration_single
            else early_expected_info.value
            if early_expected_info
            else None,
        )
        print(
            rt(
                language,
                "progressive_loading",
                images=hydration["images_seen"],
                steps=hydration["steps"],
            )
        )

    expected_info = early_expected_info
    if chapter.pages is not None:
        pages = chapter.pages
        selector_used = f"profil:{provider_name}"
    else:
        if expected_info is None:
            expected_info = detect_expected_count(page)
        provisional_single = (
            args.expected is None
            and expected_info is not None
            and expected_info.value == 1
            and expected_info.confidence != "élevée"
        )
        try:
            pages, selector_used = discover_pages(
                page,
                selector,
                None
                if provisional_single
                else expected_info.value
                if expected_info
                else None,
            )
        except RuntimeError:
            direct_document = (
                _direct_document_candidate(
                    document_candidates, page, args.output_format
                )
                if selector is None
                else None
            )
            if direct_document is not None:
                if direct_document.get("document_format") == "epub":
                    record, success = _use_direct_epub(
                        context=context,
                        candidate=direct_document,
                        chapter=chapter,
                        args=args,
                        output_dir=output_dir,
                        work_dir=work_dir,
                        publication_is_work=publication_is_work,
                        reading_mode=reading_mode,
                    )
                else:
                    record, success = _use_direct_pdf(
                        context=context,
                        candidate=direct_document,
                        chapter=chapter,
                        args=args,
                        output_dir=output_dir,
                        work_dir=work_dir,
                        publication_is_work=publication_is_work,
                        reading_mode=reading_mode,
                        reader_expected=expected_info,
                        metadata_candidates=metadata_candidates,
                        page=page,
                    )
                return page, record, success
            if not provisional_single:
                raise
            pages, selector_used = discover_pages(page, selector, 1)
        if provisional_single and len(pages) > 1:
            print("Compteur provisoire 1/1 ignoré après chargement des pages.")
            expected_info = None
    if expected_info is None:
        expected_info = _expected_from_continuous_indices(pages)
    else:
        sequence_expected = _expected_from_continuous_indices(pages)
        discrepancy = abs(expected_info.value - len(pages))
        substantial_discrepancy = discrepancy >= max(
            3,
            round(expected_info.value * 0.03),
        )
        if (
            args.expected is None
            and expected_info.confidence != "élevée"
            and sequence_expected is not None
            and len(pages) != expected_info.value
            and substantial_discrepancy
        ):
            print(
                rt(
                    language,
                    "visible_counter_ignored",
                    visible=expected_info.value,
                    count=len(pages),
                )
            )
            expected_info = sequence_expected
    expected = expected_info.value if expected_info else None

    print(
        rt(
            language,
            "detection",
            value=_localized_runtime_value(selector_used, language),
        )
    )
    print(rt(language, "resources_found", count=len(pages)))
    if expected_info:
        print(
            rt(
                language,
                "pages_expected",
                count=expected_info.value,
                source=_localized_runtime_value(expected_info.source, language),
            )
        )
        if len(pages) != expected:
            raise RuntimeError(
                f"Détection incomplète : {len(pages)}/{expected}. "
                "Corrigez --selector ou vérifiez la source."
            )

    discovered_hosts = sorted(
        {
            (urlparse(item["url"]).hostname or "").lower()
            for item in pages
            if item.get("url")
            and urlparse(item["url"]).scheme != "browser-blob"
        }
    )
    print(
        rt(
            language,
            "domains",
            value=", ".join(discovered_hosts)
            or _localized_runtime_value("ressources internes du navigateur", language),
        )
    )

    selected_output_format = (
        "cbz" if args.output_format in {"auto", "original"} else args.output_format
    )
    if args.output_format in {"auto", "original"}:
        print("Format original retenu : CBZ (pages image détectées)")

    record = {
        "index": chapter.index,
        "number": chapter.number,
        "title": chapter.title,
        "kind": chapter.kind,
        "source_url": chapter.source_url,
        "output_format": selected_output_format,
        "reading_mode": reading_mode,
        "selector": selector_used,
        "expected": expected,
        "expected_source": expected_info.source if expected_info else None,
        "detected": len(pages),
        "resource_count": len(pages),
        "resource_unit": "source_image",
    }
    if args.inspect:
        record["status"] = "inspected"
        return page, record, True

    chapter_name = _chapter_stem(chapter)
    if publication_is_work:
        artifact_dir = output_dir / (
            "volumes" if chapter.kind == "volume" else "chapters"
        )
        images_dir = (
            artifact_dir / chapter_name
            if selected_output_format == "images"
            else work_dir / chapter_name / "images"
        )
        output_stem = chapter_name
    else:
        artifact_dir = output_dir
        images_dir = (
            output_dir / "images"
            if selected_output_format == "images"
            else work_dir / "images"
        )
        output_stem = getattr(args, "output_stem", "document")

    images_dir.mkdir(parents=True, exist_ok=True)
    chapter_hosts = set(allowed_hosts)
    chapter_host = (urlparse(page.url).hostname or "").lower()
    if chapter_host:
        chapter_hosts.add(chapter_host)
    trusted_hosts = trusted_selected_resource_hosts(
        pages,
        page.url,
        chapter_hosts,
    )
    if trusted_hosts:
        chapter_hosts.update(trusted_hosts)
        for host, count in sorted(trusted_hosts.items()):
            print(
                "CDN de pages autorisé automatiquement : "
                f"{host} ({count}/{len(pages)} ressources sélectionnées)"
            )
    results, missing = download_pages(
        context=context,
        pages=pages,
        images_dir=images_dir,
        source_url=page.url,
        allowed_hosts=chapter_hosts,
        retries=args.retries,
        max_image_bytes=args.max_image_mb * 1024 * 1024,
        watermark_policy=args.watermarks,
        watermark_texts=args.watermark_text,
        workers=args.workers,
    )
    removed_total = sum(
        int(item.get("watermarks_removed") or 0) for item in results
    )
    record.update(
        {
            "saved": len(results),
            "missing": missing,
            "watermarks_removed": removed_total,
            "pages": results,
            "quality": (
                "SVG source preserved except exact watermark text; no resize"
                if removed_total
                else "original page bytes preserved; no resize"
            ),
        }
    )
    if missing:
        record["status"] = "incomplete"
        print(f"Extraction incomplète : {len(missing)} page(s) manquante(s).")
        return page, record, False

    ordered = [images_dir / item["file"] for item in results]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = create_selected_output(
        selected_output_format,
        ordered,
        artifact_dir,
        chapter.title,
        chrome_executable=Path(args.chrome),
        output_stem=output_stem,
    )
    if (
        selected_output_format in {"cbz", "cbr"}
        and ordered
        and all(path.suffix.lower() == ".svg" for path in ordered)
    ):
        record["quality"] = (
            "SVG source rendered as lossless PNG at its native viewBox size "
            "for CBZ/CBR reader compatibility"
        )
    record["artifact"] = {
        "path": _artifact_manifest_path(artifact, output_dir),
        "sha256": file_sha256(artifact) if artifact.is_file() else None,
    }
    record["status"] = "complete"
    print(rt(language, "result", value=artifact))
    return page, record, True


def run(args) -> int:
    language = getattr(args, "language", "fr")
    selector = normalize_selector_input(args.selector)
    source_host = (urlparse(args.url).hostname or "").lower()
    allowed_hosts = {
        host
        for host in {source_host, *(host.lower() for host in args.allow_host)}
        if host
    }
    if not Path(args.chrome).is_file():
        raise RuntimeError(f"Chrome introuvable : {args.chrome}")
    output_dir: Path = args.output
    port = find_free_port()

    temporary_profile = None
    if args.profile_dir:
        profile_dir = args.profile_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary_profile = tempfile.TemporaryDirectory(prefix="komaforge-profile-")
        profile_dir = Path(temporary_profile.name)

    chrome = subprocess.Popen(
        [
            args.chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            "--disable-sync",
            "about:blank",
        ]
    )
    browser = None
    try:
        wait_for_chrome(port)
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            context.add_init_script(script=BLOB_CAPTURE_INIT_SCRIPT)
            document_candidates: list[dict] = []
            metadata_candidates: list[dict] = []
            context.on(
                "response",
                lambda response: (
                    _remember_browser_document(document_candidates, response),
                    _remember_reader_metadata(metadata_candidates, response),
                ),
            )
            page = context.pages[0] if context.pages else context.new_page()

            print(rt(language, "opening", value=args.url))
            page = navigate_to_source(context, page, args.url, args.retries)

            if args.wait_for_user:
                input(
                    "Effectuez la connexion ou la validation dans Chrome, "
                    "puis appuyez sur Entrée..."
                )
            interstitial = _complete_access_check(page, args)
            if not interstitial["passed"]:
                raise RuntimeError(
                    "La vérification du site est toujours active. Relancez "
                    "avec --wait-for-user et terminez-la dans Chrome avant "
                    "de continuer."
                )
            if interstitial["encountered"]:
                print(rt(language, "access_check", seconds=interstitial["waited_ms"] / 1000))
            if args.ready_selector:
                page.locator(args.ready_selector).first.wait_for(
                    state="visible",
                    timeout=PAGE_TIMEOUT_MS,
                )

            consent = dismiss_cookie_consent(page)
            if consent:
                print(rt(language, "consent", value=consent["action"]))

            reader_entry = discover_linked_reader(context, page)
            if reader_entry and reader_entry.get("url"):
                print(
                    rt(
                        language,
                        "linked_reader",
                        action=reader_entry["action"],
                        url=reader_entry["url"],
                    )
                )
                page = navigate_to_source(
                    context,
                    page,
                    reader_entry["url"],
                    args.retries,
                )
                reader_interstitial = _complete_access_check(page, args)
                if not reader_interstitial["passed"]:
                    raise RuntimeError(
                        "Le lecteur lié reste derrière la vérification du site. "
                        "Relancez avec --wait-for-user."
                    )
                linked_consent = dismiss_cookie_consent(page)
                if linked_consent:
                    print(rt(language, "consent", value=linked_consent["action"]))
            elif reader_entry and reader_entry.get("error"):
                raise RuntimeError(
                    "Page produit eBooks détectée, mais son action "
                    f"{reader_entry['action']!r} n'a fourni aucun lecteur."
                )
            elif is_ebooks_product_url(page.url):
                availability = page.locator("body").inner_text(timeout=5_000)
                unavailable = any(
                    marker.casefold() in availability.casefold()
                    for marker in (
                        "no longer available for sale",
                        "not available in your country",
                    )
                )
                detail = (
                    " Le site indique aussi que ce titre est indisponible "
                    "à la vente ou dans la région courante."
                    if unavailable
                    else ""
                )
                raise RuntimeError(
                    "Page produit eBooks détectée, mais aucune action Preview, "
                    "Read sample ou Read online n'est exposée dans cette "
                    f"session.{detail}"
                )

            reader_landing_title = page.title().strip()
            structured_catalog = None
            if selector is None and args.scope != "document":
                structured_catalog = discover_manga_up_catalog(page, args.url)
            source_limited = bool(
                structured_catalog and structured_catalog.access_limited
            )
            if structured_catalog:
                print(
                    rt(
                        language,
                        "catalog",
                        accessible=structured_catalog.accessible_count,
                        total=structured_catalog.total_count,
                    )
                )
                if source_limited:
                    print(rt(language, "source_limit"))

            reader_gate = (
                None if structured_catalog else activate_reader_gate(page)
            )
            if reader_gate:
                print(rt(language, "reader_start", value=reader_gate["action"]))

            opened_chapter_number = None
            if reader_gate:
                try:
                    reader_text = page.locator("body").inner_text(timeout=5_000)
                    chapter_match = re.search(
                        r"\b(?:chapter|chapitre)\s*"
                        r"([0-9]+(?:\.[0-9]+)?(?:\s*-\s*[0-9]+)?)\b",
                        reader_text,
                        flags=re.IGNORECASE,
                    )
                    if chapter_match:
                        opened_chapter_number = re.sub(
                            r"\s*-\s*",
                            " -",
                            chapter_match.group(1),
                        )
                except Exception:
                    pass

            readiness = wait_for_reader_readiness(page)
            if readiness["waited_ms"]:
                print(rt(language, "reader_initialization", seconds=readiness["waited_ms"] / 1000))

            provider = (
                None
                if selector or structured_catalog
                else discover_provider(context, page, args.url)
            )
            if provider:
                allowed_hosts.update(provider.allowed_hosts)
                print(rt(language, "site_profile", value=provider.name))
                print(rt(language, "work", value=provider.title))
                all_chapters = [
                    ChapterTask(
                        index=chapter.index,
                        number=chapter.number,
                        title=chapter.title,
                        source_url=chapter.source_url or args.url,
                        pages=chapter.pages,
                        expected=chapter.expected,
                        kind="book" if provider.publication_type == "book" else "chapter",
                    )
                    for chapter in provider.chapters
                ]
                publication_title = provider.title
                publication_type = provider.publication_type
            else:
                chapter_links = (
                    list(structured_catalog.chapters)
                    if structured_catalog
                    else []
                )
                selectable_parts = []
                should_discover_work = (
                    selector is None
                    and args.scope != "document"
                    and (
                        args.scope == "work"
                        or not looks_like_chapter_url(args.url)
                    )
                )
                if should_discover_work and not chapter_links:
                    chapter_links = discover_chapters(
                        page,
                        args.url,
                        minimum=2 if args.scope == "work" else 3,
                    )
                    if not chapter_links:
                        selectable_parts = discover_selectable_parts(
                            page,
                            minimum=2,
                            wait_timeout_ms=10_000,
                        )
                if args.scope == "work" and not chapter_links and not selectable_parts:
                    raise RuntimeError(
                        "Aucune liste fiable de chapitres ou volumes n'a été "
                        "trouvée sur cette URL."
                    )
                publication_title = (
                    reader_landing_title
                    if reader_gate and reader_landing_title
                    else page.title().strip() or output_dir.name
                )
                if opened_chapter_number:
                    publication_title = publication_folder_title(
                        publication_title,
                        args.url,
                    )
                    if not re.search(
                        r"\b(?:chapter|chapitre)\s*"
                        + re.escape(opened_chapter_number)
                        + r"\b",
                        publication_title,
                        flags=re.IGNORECASE,
                    ):
                        publication_title = (
                            f"{publication_title} - Chapter "
                            f"{opened_chapter_number}"
                        )
                if chapter_links:
                    publication_type = "work"
                    all_chapters = [
                        ChapterTask(
                            index=chapter.index,
                            number=chapter.number,
                            title=chapter.title,
                            source_url=chapter.url,
                            kind="chapter",
                        )
                        for chapter in chapter_links
                    ]
                elif selectable_parts:
                    publication_type = "collection"
                    all_chapters = [
                        ChapterTask(
                            index=part.index,
                            number=part.number,
                            title=part.title,
                            source_url=args.url,
                            kind=part.kind,
                            control_selector=part.selector,
                            control_value=part.value,
                        )
                        for part in selectable_parts
                    ]
                else:
                    publication_type = (
                        "chapter" if opened_chapter_number else "document"
                    )
                    all_chapters = [
                        ChapterTask(
                            index=1,
                            number=opened_chapter_number or "1",
                            title=publication_title,
                            source_url=args.url,
                            kind=(
                                "chapter" if opened_chapter_number else "document"
                            ),
                        )
                    ]

            publication_is_work = (
                publication_type == "work" or len(all_chapters) > 1
            )
            print(rt(language, "structure", value=publication_type))
            part_kind = all_chapters[0].kind if all_chapters else "part"
            agreement = "détectées" if part_kind == "part" else "détectés"
            print(
                rt(
                    language,
                    "parts_detected",
                    label=_part_label(part_kind, plural=True, language=language),
                    count=len(all_chapters),
                )
            )
            if publication_is_work:
                chapters_to_display = (
                    all_chapters
                    if args.chapters == "ask"
                    else select_chapters(all_chapters, args.chapters)
                )
                for chapter in chapters_to_display[:30]:
                    print(
                        f"  {chapter.index}. {chapter.title} — "
                        f"{chapter.source_url}"
                    )
                if len(chapters_to_display) > 30:
                    print(f"  … et {len(chapters_to_display) - 30} autre(s)")
                selected_chapters = resolve_part_selection(
                    all_chapters,
                    args.chapters,
                    part_kind,
                    default_expression=("all" if structured_catalog else "1"),
                    language=language,
                )
                if len(selected_chapters) != len(all_chapters):
                    agreement = (
                        "sélectionnées" if part_kind == "part" else "sélectionnés"
                    )
                    print(
                        rt(
                            language,
                            "parts_selected",
                            label=_part_label(part_kind, plural=True, language=language),
                            count=len(selected_chapters),
                        )
                    )
            else:
                selected_chapters = all_chapters

            output_title = publication_folder_title(
                publication_title,
                args.url,
                publication_is_work=publication_is_work,
            )
            if getattr(args, "output_auto_named", False):
                output_dir = choose_title_output_dir(
                    args.output_root,
                    output_title,
                    args.url,
                    expected_manifest=(
                        "publication.json" if publication_is_work else "pages.json"
                    ),
                )
            elif not args.inspect:
                ensure_output_dir_is_compatible(output_dir, args.url)
            work_dir = output_dir / ".komaforge-work"
            args.output_stem = (
                safe_slug(output_title)
                if getattr(args, "output_auto_named", False)
                else "document"
            )
            if args.inspect:
                print(rt(language, "detected_title", value=output_title))
                print(rt(language, "planned_folder", value=output_dir))
            else:
                print(rt(language, "detected_title", value=output_title))
                print(rt(language, "final_folder", value=output_dir))

            manifest_path = output_dir / (
                "publication.json" if publication_is_work else "pages.json"
            )
            manifest = {
                "source_url": args.url,
                "provider": provider.name if provider else None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "output_format": args.output_format,
                "watermark_policy": args.watermarks,
                "watermark_texts": args.watermark_text,
                "publication": {
                    "type": publication_type,
                    "title": output_title,
                    "source_title": publication_title,
                    "part_kind": part_kind,
                    "part_count": len(all_chapters),
                    "selected_part_count": len(selected_chapters),
                    "chapter_count": len(all_chapters),
                    "selected_chapter_count": len(selected_chapters),
                    "chapters": [],
                },
            }
            if structured_catalog:
                manifest["publication"]["availability"] = {
                    "catalog_part_count": structured_catalog.total_count,
                    "accessible_part_count": structured_catalog.accessible_count,
                    "selected_accessible_part_count": len(selected_chapters),
                    "access_limited": structured_catalog.access_limited,
                    "source": structured_catalog.source,
                }
            completed = True
            chapter_records: list[dict] = []
            for position, chapter in enumerate(selected_chapters):
                reuse_current_page = (
                    chapter.pages is not None
                    or chapter.control_selector is not None
                    or (not publication_is_work and position == 0)
                )
                try:
                    page, record, success = extract_chapter(
                        context=context,
                        page=page,
                        chapter=chapter,
                        args=args,
                        selector=selector,
                        allowed_hosts=allowed_hosts,
                        output_dir=output_dir,
                        work_dir=work_dir,
                        publication_is_work=publication_is_work,
                        provider_name=provider.name if provider else None,
                        reuse_current_page=reuse_current_page,
                        document_candidates=document_candidates,
                        metadata_candidates=metadata_candidates,
                    )
                except Exception as exc:
                    if not publication_is_work:
                        raise
                    success = False
                    record = {
                        "index": chapter.index,
                        "number": chapter.number,
                        "title": chapter.title,
                        "kind": chapter.kind,
                        "source_url": chapter.source_url,
                        "status": "error",
                        "error": str(exc),
                    }
                    print(f"[ÉCHEC] {chapter.title} : {exc}")
                    live_pages = [
                        candidate
                        for candidate in context.pages
                        if not candidate.is_closed()
                    ]
                    page = live_pages[-1] if live_pages else context.new_page()
                completed = completed and success
                chapter_records.append(record)
                record_output_format = record.get("output_format")
                if args.output_format in {"auto", "original"} and record_output_format:
                    current_output_format = manifest["output_format"]
                    if current_output_format in {"auto", "original"}:
                        manifest["output_format"] = record_output_format
                    elif current_output_format != record_output_format:
                        manifest["output_format"] = "mixed"
                manifest["publication"]["chapters"] = chapter_records
                if publication_is_work and not args.inspect:
                    manifest["publication"]["status"] = (
                        "limited_by_source"
                        if completed and source_limited
                        else "complete"
                        if completed
                        else "incomplete"
                    )
                    write_json(manifest_path, manifest)

            if source_limited and structured_catalog:
                print(
                    rt(
                        language,
                        "source_result",
                        accessible=structured_catalog.accessible_count,
                        total=structured_catalog.total_count,
                    )
                )
            if args.inspect:
                if completed:
                    print(rt(language, "inspection_complete"))
                else:
                    print(rt(language, "inspection_incomplete"))
                return 0 if completed else 2

            manifest["publication"]["chapters"] = chapter_records
            manifest["publication"]["status"] = (
                "limited_by_source"
                if completed and source_limited
                else "complete"
                if completed
                else "incomplete"
            )
            if not publication_is_work:
                record = chapter_records[0]
                manifest["publication"]["chapters"] = [
                    {
                        "index": record["index"],
                        "number": record["number"],
                        "title": record["title"],
                        "kind": record["kind"],
                        "source_url": record["source_url"],
                        "page_count": record.get("detected", 0),
                        "status": record.get("status"),
                    }
                ]
                for key in (
                    "reading_mode",
                    "selector",
                    "expected",
                    "expected_source",
                    "detected",
                    "resource_count",
                    "resource_unit",
                    "reader_expected",
                    "source_visible_page_count",
                    "recovered_from_detached_tree",
                    "saved",
                    "missing",
                    "missing_count",
                    "quality",
                    "pdf_diagnostics",
                    "epub_spine_items",
                    "epub_diagnostics",
                    "render_dpi",
                    "source_sha256",
                    "watermarks_removed",
                    "pages",
                    "artifact",
                ):
                    if key in record:
                        manifest[key] = record[key]
            write_json(manifest_path, manifest)
            if completed and args.output_format != "images" and work_dir.exists():
                remove_validated_work_directory(work_dir, output_dir)
            print(rt(language, "manifest", value=manifest_path))
            return 0 if completed else 2
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
            cleanup_temporary_profile(temporary_profile, profile_dir)
