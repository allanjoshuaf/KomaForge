"""Validated page-resource downloads with resumable browser fallback."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from .formats import file_sha256
from .resources import detect_resource, is_page_resource, resource_from_url_value
from .svg_tools import inspect_svg, remove_exact_watermarks


REQUEST_TIMEOUT_MS = 45_000


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
                    content_type = str(item.get("_embedded_content_type") or "")
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
