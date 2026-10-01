from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
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
from .formats import (
    create_pdf_from_epub_bytes,
    create_selected_output,
    file_sha256,
    remove_validated_work_directory,
    render_pdf_bytes_to_images,
)
from .epub_transport import fetch_browser_epub as _fetch_browser_epub
from .legacy_bridge import normalize_legacy_manifest
from .models import Confidence, Part, Publication, ResourceKind
from .page_download import (
    download_pages,
    host_is_allowed,
    sniff_extension,
    trusted_selected_resource_hosts,
    valid_existing_file,
)
from .paths import (
    canonical_source_identity,
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
from .sources import SourceAdapter, SourceReference, SourceSession
from .terminal_ui import rt


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
    adapter_part: Part | None = None


def _chapter_record_identity(record: dict) -> tuple[str, str]:
    return (
        canonical_source_identity(str(record.get("source_url") or "")),
        str(record.get("number") or ""),
    )


def merge_chapter_records(
    existing: list[dict],
    current: list[dict],
) -> list[dict]:
    """Keep downloaded work parts while replacing matching refreshed records."""

    merged: dict[tuple[str, str], dict] = {}
    for record in (*existing, *current):
        if not isinstance(record, dict):
            raise ValueError("chapter records must be dictionaries")
        identity = _chapter_record_identity(record)
        if not identity[0]:
            raise ValueError("chapter record source URL cannot be empty")
        previous = merged.get(identity)
        if (
            previous is not None
            and record.get("status") == "error"
            and previous.get("status") == "complete"
        ):
            continue
        merged[identity] = record

    def order(record: dict) -> tuple[int, str, str]:
        try:
            position = int(record.get("index"))
        except (TypeError, ValueError):
            position = 2**31 - 1
        identity = _chapter_record_identity(record)
        return position, identity[1], identity[0]

    return sorted(merged.values(), key=order)


def _existing_chapter_records(manifest_path: Path, source_url: str) -> list[dict]:
    if not manifest_path.is_file():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if canonical_source_identity(str(payload.get("source_url") or "")) != (
        canonical_source_identity(source_url)
    ):
        raise RuntimeError("existing publication manifest belongs to another source")
    publication = payload.get("publication")
    records = publication.get("chapters") if isinstance(publication, dict) else None
    if not isinstance(records, list):
        raise RuntimeError("existing publication manifest has no chapter records")
    return [dict(record) for record in records]


def _chapter_tasks_from_publication(
    publication: Publication,
) -> list[ChapterTask]:
    """Translate normalized adapter output into Core's download work items."""

    confidence_labels = {
        Confidence.LOW: "faible",
        Confidence.MEDIUM: "moyenne",
        Confidence.HIGH: "élevée",
    }
    tasks: list[ChapterTask] = []
    for part in sorted(publication.parts, key=lambda item: item.position):
        pages = [
            {
                "page": resource.position,
                "url": resource.locator,
                **dict(resource.metadata),
            }
            for resource in sorted(part.resources, key=lambda item: item.position)
        ]
        coverage = part.coverage
        expected = (
            ExpectedCount(
                coverage.expected,
                coverage.evidence or f"adaptateur {publication.source_id}",
                confidence_labels[coverage.confidence],
            )
            if coverage is not None and coverage.expected is not None
            else None
        )
        kind = part.kind.value
        if (
            kind == "document"
            and publication.metadata.get("publication_type") == "book"
        ):
            kind = "book"
        tasks.append(
            ChapterTask(
                index=part.position,
                number=part.number or str(part.position),
                title=part.title,
                source_url=part.source_url,
                pages=pages or None,
                expected=expected,
                kind=kind,
                adapter_part=part,
            )
        )
    return tasks


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
    if incomplete and recover_requested:
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
            manifest = {
                "source_url": args.url,
                "provider": provider_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "output_format": args.output_format,
                "watermark_policy": args.watermarks,
                "watermark_texts": args.watermark_text,
                "publication": {
                    "type": publication_type,
                    "title": output_title,
                    "source_title": publication_title,
                    "source_metadata": (
                        dict(adapter_publication.metadata)
                        if adapter_publication is not None
                        else {}
                    ),
                    "part_kind": part_kind,
                    "part_count": len(all_chapters),
                    "selected_part_count": len(selected_chapters),
                    "chapter_count": len(all_chapters),
                    "selected_chapter_count": len(selected_chapters),
                    "chapters": [],
                },
            }
            if adapter_publication and catalog_coverage:
                manifest["publication"]["availability"] = {
                    "catalog_part_count": catalog_coverage.expected,
                    "accessible_part_count": catalog_coverage.available,
                    "selected_accessible_part_count": len(selected_chapters),
                    "access_limited": source_limited,
                    "source": catalog_coverage.evidence,
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
                stored_chapters = merge_chapter_records(
                    existing_chapter_records,
                    chapter_records,
                )
                manifest["publication"]["chapters"] = stored_chapters
                manifest["publication"]["selected_part_count"] = len(stored_chapters)
                manifest["publication"]["selected_chapter_count"] = len(stored_chapters)
                if "availability" in manifest["publication"]:
                    manifest["publication"]["availability"][
                        "selected_accessible_part_count"
                    ] = len(stored_chapters)
                if publication_is_work and not args.inspect:
                    work_complete = (
                        completed
                        and len(stored_chapters) >= len(all_chapters)
                        and all(
                            item.get("status") == "complete"
                            for item in stored_chapters
                        )
                    )
                    manifest["publication"]["status"] = (
                        "limited_by_source"
                        if work_complete and source_limited
                        else "complete"
                        if work_complete
                        else "incomplete"
                    )
                    write_json(manifest_path, manifest)

            stored_chapters = (
                merge_chapter_records(existing_chapter_records, chapter_records)
                if publication_is_work and not args.inspect
                else chapter_records
            )
            manifest["publication"]["chapters"] = stored_chapters
            manifest["publication"]["selected_part_count"] = len(stored_chapters)
            manifest["publication"]["selected_chapter_count"] = len(stored_chapters)
            if "availability" in manifest["publication"]:
                manifest["publication"]["availability"][
                    "selected_accessible_part_count"
                ] = len(stored_chapters)
            work_complete = (
                completed
                and (
                    not publication_is_work
                    or (
                        len(stored_chapters) >= len(all_chapters)
                        and all(
                            item.get("status") == "complete"
                            for item in stored_chapters
                        )
                    )
                )
            )
            manifest["publication"]["status"] = (
                "limited_by_source"
                if work_complete and source_limited
                else "complete"
                if work_complete
                else "incomplete"
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
