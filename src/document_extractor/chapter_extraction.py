"""Inspection et extraction d'une partie dans une session préparée."""

from __future__ import annotations
from .diagnostic_ui import diagnostic_print as print, diagnostic_input as input

from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse


from .browser_session import PAGE_TIMEOUT_MS, navigate_to_source
from .chapter_tasks import (
    ChapterTask,
    chapter_stem as _chapter_stem,
    expected_from_continuous_indices as _expected_from_continuous_indices,
    localized_runtime_value as _localized_runtime_value,
    part_label as _part_label,
)
from .detection import (
    ExpectedCount,
    access_interstitial_state,
    activate_reader_gate,
    activate_reading_mode,
    detect_expected_count,
    dismiss_cookie_consent,
    discover_pages,
    hydrate_lazy_content,
    wait_for_access_interstitial,
    wait_for_reader_readiness,
)
from .formats import file_sha256
from .models import Confidence, ResourceKind
from .page_output import produce_page_document
from .sources import SourceAdapter, SourceSession
from .terminal_ui import rt


from .direct_document import _use_direct_pdf, _use_direct_epub

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


def _artifact_manifest_path(artifact: Path, output_dir: Path) -> str:
    try:
        return artifact.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return str(artifact)


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
    source_adapter: SourceAdapter | None = None,
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

    adapter_pages_loaded = False
    if (
        chapter.pages is None
        and chapter.adapter_part is not None
        and source_adapter is not None
    ):
        resource_set = source_adapter.get_resources(
            chapter.adapter_part,
            SourceSession(
                browser_context=context,
                page=page,
                request=context.request,
                options={
                    "inspect": args.inspect,
                    "scope": args.scope,
                    "selector": selector,
                    "expected": args.expected,
                    "reading_mode_selector": args.reading_mode_selector,
                    "reading_mode_value": args.reading_mode_value,
                    "document_candidates": document_candidates,
                    "resource_progress": lambda current, total: print(
                        f"Rendu du lecteur : page {current}/{total}"
                    ),
                    "access_gate_prompt": (
                        input if getattr(args, "wait_for_user", False) else None
                    ),
                },
            ),
        )
        if resource_set.resources and all(
            resource.kind in {ResourceKind.IMAGE, ResourceKind.SVG}
            for resource in resource_set.resources
        ):
            confidence_labels = {
                Confidence.LOW: "faible",
                Confidence.MEDIUM: "moyenne",
                Confidence.HIGH: "élevée",
            }
            coverage = resource_set.coverage
            chapter = replace(
                chapter,
                pages=[
                    {
                        "page": resource.position,
                        "url": resource.locator,
                        **dict(resource.metadata),
                    }
                    for resource in resource_set.resources
                ],
                expected=(
                    ExpectedCount(
                        coverage.expected,
                        coverage.evidence or f"adaptateur {source_adapter.id}",
                        confidence_labels[coverage.confidence],
                    )
                    if coverage.expected is not None
                    else None
                ),
            )
            adapter_pages_loaded = True

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
        selector_used = (
            f"adaptateur:{source_adapter.id}"
            if adapter_pages_loaded and source_adapter is not None
            else f"profil:{provider_name}"
        )
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

    produced = produce_page_document(
        context=context,
        pages=pages,
        images_dir=images_dir,
        artifact_dir=artifact_dir,
        source_url=page.url,
        page_url=page.url,
        allowed_hosts=allowed_hosts,
        retries=args.retries,
        max_image_bytes=args.max_image_mb * 1024 * 1024,
        watermark_policy=args.watermarks,
        watermark_texts=args.watermark_text,
        workers=args.workers,
        selected_output_format=selected_output_format,
        title=chapter.title,
        chrome_executable=Path(args.chrome),
        output_stem=output_stem,
    )
    record.update(
        {
            "saved": len(produced.pages),
            "missing": produced.missing,
            "watermarks_removed": produced.watermarks_removed,
            "pages": produced.pages,
            "quality": produced.quality,
        }
    )
    if produced.missing:
        record["status"] = "incomplete"
        print(
            f"Extraction incomplète : {len(produced.missing)} "
            "page(s) manquante(s)."
        )
        return page, record, False

    if produced.artifact is None:
        raise RuntimeError("La production des pages n'a créé aucun artefact.")
    record["artifact"] = {
        "path": _artifact_manifest_path(produced.artifact, output_dir),
        "sha256": (
            file_sha256(produced.artifact)
            if produced.artifact.is_file()
            else None
        ),
    }
    record["status"] = "complete"
    print(rt(language, "result", value=produced.artifact))
    return page, record, True
