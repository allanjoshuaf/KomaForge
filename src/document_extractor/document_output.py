"""Production des artefacts issus de documents PDF ou EPUB directs."""

from __future__ import annotations
from .diagnostic_ui import diagnostic_print as print, diagnostic_input as input

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .formats import (
    create_pdf_from_epub_bytes,
    create_selected_output,
    render_pdf_bytes_to_images,
)


@dataclass(frozen=True)
class ProducedDocument:
    artifact: Path
    saved: int
    quality: str
    resource_unit: str
    source_sha256: str
    detected: int | None = None
    render_dpi: int | None = None


def produce_pdf_document(
    *,
    data: bytes,
    page_count: int,
    selected_output_format: str,
    artifact_dir: Path,
    output_stem: str,
    title: str,
    chrome_executable: Path,
    images_dir: Path | None = None,
    recovered_from_detached_tree: bool = False,
) -> ProducedDocument:
    """Écrit ou convertit un PDF déjà récupéré et validé."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_sha256 = hashlib.sha256(data).hexdigest()

    if selected_output_format == "pdf":
        artifact = artifact_dir / f"{output_stem}.pdf"
        artifact.write_bytes(data)
        quality = (
            "original page objects reassembled; no rasterization"
            if recovered_from_detached_tree
            else "original PDF bytes preserved; no re-encoding"
        )
        return ProducedDocument(
            artifact=artifact,
            saved=page_count,
            quality=quality,
            resource_unit="pdf_document",
            source_sha256=source_sha256,
        )

    if images_dir is None:
        raise ValueError("images_dir est requis pour convertir un PDF")
    print(
        "Conversion demandée : rendu des pages PDF en PNG à 200 ppp "
        f"pour produire {selected_output_format.upper()}."
    )
    rendered = render_pdf_bytes_to_images(data, images_dir, dpi=200)
    artifact = create_selected_output(
        selected_output_format,
        rendered,
        artifact_dir,
        title,
        chrome_executable=chrome_executable,
        output_stem=output_stem,
    )
    return ProducedDocument(
        artifact=artifact,
        saved=page_count,
        quality=(
            "PDF pages rasterized losslessly to PNG at 200 dpi for "
            f"{selected_output_format}"
        ),
        resource_unit="rendered_pdf_page",
        source_sha256=source_sha256,
        render_dpi=200,
    )


def produce_epub_document(
    *,
    data: bytes,
    spine_count: int,
    selected_output_format: str,
    artifact_dir: Path,
    output_stem: str,
    title: str,
    chrome_executable: Path,
    converted_pdf: Path,
    images_dir: Path | None = None,
    cleanup_dirs: tuple[Path, ...] = (),
) -> ProducedDocument:
    """Écrit ou convertit un EPUB déjà récupéré et validé."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_sha256 = hashlib.sha256(data).hexdigest()

    if selected_output_format == "epub":
        artifact = artifact_dir / f"{output_stem}.epub"
        artifact.write_bytes(data)
        return ProducedDocument(
            artifact=artifact,
            saved=spine_count,
            quality="original EPUB bytes preserved; no re-encoding",
            resource_unit="epub_document",
            source_sha256=source_sha256,
        )

    converted_pdf.parent.mkdir(parents=True, exist_ok=True)
    print(
        "Conversion EPUB : impression des sections XHTML avec Chrome "
        "en conservant texte, images et mise en forme."
    )
    converted_pdf, conversion = create_pdf_from_epub_bytes(
        data,
        converted_pdf,
        chrome_executable,
    )
    page_count = int(conversion["page_count"])
    print(f"Pages produites après mise en pages EPUB : {page_count}")

    if selected_output_format == "pdf":
        artifact = artifact_dir / f"{output_stem}.pdf"
        converted_pdf.replace(artifact)
        quality = "reflowable EPUB printed to vector/text PDF with Chrome"
        resource_unit = "epub_document"
        render_dpi = None
    else:
        if images_dir is None:
            raise ValueError("images_dir est requis pour convertir un EPUB")
        rendered = render_pdf_bytes_to_images(
            converted_pdf.read_bytes(), images_dir, dpi=200
        )
        converted_pdf.unlink(missing_ok=True)
        if selected_output_format == "images":
            for empty_dir in cleanup_dirs:
                try:
                    empty_dir.rmdir()
                except OSError:
                    pass
        artifact = create_selected_output(
            selected_output_format,
            rendered,
            artifact_dir,
            title,
            chrome_executable=chrome_executable,
            output_stem=output_stem,
        )
        quality = (
            "EPUB laid out with Chrome then rasterized losslessly to PNG "
            f"at 200 dpi for {selected_output_format}"
        )
        resource_unit = "rendered_epub_page"
        render_dpi = 200

    return ProducedDocument(
        artifact=artifact,
        saved=page_count,
        quality=quality,
        resource_unit=resource_unit,
        source_sha256=source_sha256,
        detected=page_count,
        render_dpi=render_dpi,
    )
