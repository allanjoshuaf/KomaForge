"""Traitement et couverture des documents directs observés dans le lecteur."""

from __future__ import annotations
from .diagnostic_ui import diagnostic_print as print, diagnostic_input as input

import hashlib
from pathlib import Path

from .chapter_tasks import ChapterTask, chapter_stem as _chapter_stem
from .detection import ExpectedCount
from .document_output import produce_epub_document, produce_pdf_document
from .epub_transport import fetch_browser_epub as _fetch_browser_epub
from .formats import file_sha256
from .pdf_structure import recover_detached_page_tree
from .pdf_transport import fetch_browser_pdf as _fetch_browser_pdf
from .reader_metadata import wait_for_publication_total as _wait_for_publication_total
from .terminal_ui import rt


def _artifact_manifest_path(artifact: Path, output_dir: Path) -> str:
    try:
        return artifact.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return str(artifact)


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
    images_dir = None
    if selected_output_format != "pdf":
        images_dir = (
            artifact_dir / output_stem
            if selected_output_format == "images" and publication_is_work
            else output_dir / "images"
            if selected_output_format == "images"
            else work_dir / output_stem / "images"
            if publication_is_work
            else work_dir / "images"
        )
    produced = produce_pdf_document(
        data=data,
        page_count=page_count,
        selected_output_format=selected_output_format,
        artifact_dir=artifact_dir,
        output_stem=output_stem,
        title=chapter.title,
        chrome_executable=Path(args.chrome),
        images_dir=images_dir,
        recovered_from_detached_tree=recovery is not None and not incomplete,
    )
    record["saved"] = produced.saved
    record["quality"] = produced.quality
    record["resource_unit"] = produced.resource_unit
    if produced.render_dpi is not None:
        record["render_dpi"] = produced.render_dpi
    record["artifact"] = {
        "path": _artifact_manifest_path(produced.artifact, output_dir),
        "sha256": (
            file_sha256(produced.artifact)
            if produced.artifact.is_file()
            else None
        ),
        "source_sha256": produced.source_sha256,
    }
    record["status"] = "complete"
    print(rt(language, "result", value=produced.artifact))
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
    converted_pdf = work_dir / output_stem / "source-rendered.pdf"
    images_dir = None
    if selected_output_format not in {"epub", "pdf"}:
        images_dir = (
            artifact_dir / output_stem
            if selected_output_format == "images" and publication_is_work
            else output_dir / "images"
            if selected_output_format == "images"
            else work_dir / output_stem / "images"
        )
    produced = produce_epub_document(
        data=data,
        spine_count=spine_count,
        selected_output_format=selected_output_format,
        artifact_dir=artifact_dir,
        output_stem=output_stem,
        title=chapter.title,
        chrome_executable=Path(args.chrome),
        converted_pdf=converted_pdf,
        images_dir=images_dir,
        cleanup_dirs=(converted_pdf.parent, work_dir),
    )
    record["saved"] = produced.saved
    record["quality"] = produced.quality
    record["resource_unit"] = produced.resource_unit
    if produced.detected is not None:
        record["detected"] = produced.detected
    if produced.render_dpi is not None:
        record["render_dpi"] = produced.render_dpi

    record["artifact"] = {
        "path": _artifact_manifest_path(produced.artifact, output_dir),
        "sha256": (
            file_sha256(produced.artifact)
            if produced.artifact.is_file()
            else None
        ),
        "source_sha256": produced.source_sha256,
    }
    record["status"] = "complete"
    print(rt(language, "result", value=produced.artifact))
    return record, True
