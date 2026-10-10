from __future__ import annotations
from .diagnostic_ui import diagnostic_print as print, diagnostic_input as input

import hashlib
import re
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .application import load_source_publication, resolve_source
from .browser_session import (
    PAGE_TIMEOUT_MS,
    cleanup_temporary_profile,
    find_free_port,
    navigate_to_source,
    wait_for_chrome,
)
from .chapter_tasks import (
    ChapterTask,
    chapter_stem as _chapter_stem,
    chapter_tasks_from_publication as _chapter_tasks_from_publication,
    existing_chapter_records as _existing_chapter_records,
    expected_from_continuous_indices as _expected_from_continuous_indices,
    localized_runtime_value as _localized_runtime_value,
    merge_chapter_records,
    part_label as _part_label,
    resolve_part_selection,
)
from .detection import (
    BLOB_CAPTURE_INIT_SCRIPT,
    ExpectedCount,
    access_interstitial_state,
    activate_reader_gate,
    activate_reading_mode,
    discover_chapters,
    discover_linked_reader,
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
from .document_output import produce_epub_document, produce_pdf_document
from .formats import (
    file_sha256,
    remove_validated_work_directory,
)
from .epub_transport import fetch_browser_epub as _fetch_browser_epub
from .legacy_bridge import normalize_legacy_manifest
from .models import Confidence, ResourceKind
from .page_download import (
    download_pages,
    host_is_allowed,
    sniff_extension,
    trusted_selected_resource_hosts,
    valid_existing_file,
)
from .page_output import produce_page_document
from .paths import (
    choose_title_output_dir,
    ensure_output_dir_is_compatible,
    publication_folder_title,
    safe_slug,
)
from .pdf_structure import recover_detached_page_tree
from .pdf_transport import (
    fetch_browser_pdf as _fetch_browser_pdf,
    fetch_pdf_in_ranges as _fetch_pdf_in_ranges,
)
from .reader_metadata import (
    page_count_candidates as _page_count_candidates,
    reader_publication_total as _reader_publication_total,
    remember_browser_document as _remember_browser_document,
    remember_reader_metadata as _remember_reader_metadata,
    wait_for_publication_total as _wait_for_publication_total,
)
from .publication_manifest import (
    create_publication_manifest,
    flatten_single_document_manifest,
    select_stored_chapter_records,
    update_manifest_progress,
    write_json,
)
from .sources import SourceAdapter, SourceReference, SourceSession
from .terminal_ui import rt


from .chapter_extraction import (
    _artifact_manifest_path,
    _complete_access_check,
    _direct_document_candidate,
    _wait_for_selected_part,
    extract_chapter,
)
from .direct_document import (
    _ask_interactive_detached_recovery,
    _use_direct_epub,
    _use_direct_pdf,
)


def run(args) -> int:
    from .diagnostic_ui import set_diagnostic_language
    set_diagnostic_language(getattr(args, "language", "fr"))
    language = getattr(args, "language", "fr")
    source_route = resolve_source(args.url)
    selector = normalize_selector_input(args.selector)
    source_host = (urlparse(args.url).hostname or "").lower()
    allowed_hosts = {
        host
        for host in {
            source_host,
            *(host.lower() for host in args.allow_host),
            *(
                host.lower()
                for host in getattr(source_route.adapter, "network_domains", ())
            ),
        }
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
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
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

            source_landing_title = page.title().strip()
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
            use_source_adapter = selector is None and source_route.specialized
            reader_gate = None if use_source_adapter else activate_reader_gate(page)
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

            adapter_publication = None
            if use_source_adapter:
                source_session = SourceSession(
                    browser_context=context,
                    page=page,
                    request=context.request,
                    options={
                        "scope": args.scope,
                        "product_url": args.url,
                        "title": source_landing_title or reader_landing_title,
                        "document_candidates": document_candidates,
                    },
                )
                adapter_publication = load_source_publication(
                    source_route,
                    SourceReference(
                        source_id=source_route.adapter.id,
                        value=args.url,
                        url=args.url,
                    ),
                    source_session,
                )

            catalog_coverage = (
                adapter_publication.coverage
                if adapter_publication is not None
                and adapter_publication.coverage is not None
                and adapter_publication.coverage.unit == "parts"
                else None
            )
            source_limited = bool(
                catalog_coverage
                and catalog_coverage.status.value == "source_limited"
            )
            if adapter_publication and catalog_coverage:
                print(
                    rt(
                        language,
                        "catalog",
                        source=source_route.adapter.name,
                        accessible=catalog_coverage.available,
                        total=catalog_coverage.expected,
                    )
                )
                if source_limited:
                    print(rt(language, "source_limit"))

            provider_name = None
            if adapter_publication:
                provider = adapter_publication.metadata.get("provider")
                provider_name = str(provider) if provider else None
                allowed_hosts.update(
                    str(host)
                    for host in adapter_publication.metadata.get("allowed_hosts", ())
                )
                if provider_name:
                    print(rt(language, "site_profile", value=provider_name))
                publication_title = adapter_publication.title
                publication_type = str(
                    adapter_publication.metadata.get("publication_type")
                    or (
                        "work"
                        if len(adapter_publication.parts) > 1
                        else "document"
                    )
                )
                if publication_type == "work":
                    print(rt(language, "work", value=adapter_publication.title))
                all_chapters = _chapter_tasks_from_publication(adapter_publication)
            else:
                chapter_links = []
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
                    default_expression=("all" if adapter_publication else "1"),
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
            existing_chapter_records = (
                _existing_chapter_records(manifest_path, args.url)
                if publication_is_work and not args.inspect
                else []
            )
            manifest = create_publication_manifest(
                source_url=args.url,
                provider=provider_name,
                requested_output_format=args.output_format,
                watermark_policy=args.watermarks,
                watermark_texts=args.watermark_text,
                publication_type=publication_type,
                output_title=output_title,
                source_title=publication_title,
                source_metadata=(
                    dict(adapter_publication.metadata)
                    if adapter_publication is not None
                    else {}
                ),
                part_kind=part_kind,
                part_count=len(all_chapters),
                selected_part_count=len(selected_chapters),
                catalog_part_count=(
                    catalog_coverage.expected if catalog_coverage else None
                ),
                accessible_part_count=(
                    catalog_coverage.available if catalog_coverage else None
                ),
                source_limited=source_limited,
                availability_source=(
                    catalog_coverage.evidence if catalog_coverage else None
                ),
            )
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
                        provider_name=provider_name,
                        reuse_current_page=reuse_current_page,
                        document_candidates=document_candidates,
                        metadata_candidates=metadata_candidates,
                        source_adapter=(
                            source_route.adapter
                            if adapter_publication is not None
                            else None
                        ),
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
                stored_chapters = select_stored_chapter_records(
                    existing_chapter_records,
                    chapter_records,
                    publication_is_work=publication_is_work,
                    inspect=args.inspect,
                )
                if publication_is_work and not args.inspect:
                    update_manifest_progress(
                        manifest,
                        stored_chapters,
                        completed=completed,
                        publication_is_work=True,
                        all_part_count=len(all_chapters),
                        source_limited=source_limited,
                    )
                    write_json(manifest_path, manifest)

            stored_chapters = select_stored_chapter_records(
                existing_chapter_records,
                chapter_records,
                publication_is_work=publication_is_work,
                inspect=args.inspect,
            )
            update_manifest_progress(
                manifest,
                stored_chapters,
                completed=completed,
                publication_is_work=publication_is_work,
                all_part_count=len(all_chapters),
                source_limited=source_limited,
            )
            normalize_legacy_manifest(manifest, source_route.adapter.id)

            if source_limited and catalog_coverage:
                print(
                    rt(
                        language,
                        "source_result",
                        accessible=catalog_coverage.available,
                        total=catalog_coverage.expected,
                    )
                )
            if args.inspect:
                args.inspection_manifest = manifest
                if completed:
                    print(rt(language, "inspection_complete"))
                else:
                    print(rt(language, "inspection_incomplete"))
                return 0 if completed else 2

            if not publication_is_work:
                record = chapter_records[0]
                flatten_single_document_manifest(manifest, record)
            write_json(manifest_path, manifest)
            if completed:
                try:
                    from .library import LibraryIndex

                    library_index = LibraryIndex(
                        args.output_root / ".komaforge" / "library.sqlite"
                    )
                    library_index.rebuild(args.output_root)
                    print(rt(language, "library_updated", value=library_index.path))
                except (OSError, RuntimeError, ValueError) as exc:
                    print(rt(language, "library_update_failed", value=type(exc).__name__))
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
