"""Production d'un artefact à partir de pages image ou SVG détectées."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .formats import create_selected_output
from .page_download import download_pages, trusted_selected_resource_hosts


@dataclass(frozen=True)
class ProducedPages:
    artifact: Path | None
    pages: list[dict]
    missing: list[int]
    watermarks_removed: int
    quality: str
    trusted_hosts: dict[str, int]


def produce_page_document(
    *,
    context,
    pages: list[dict],
    images_dir: Path,
    artifact_dir: Path,
    source_url: str,
    page_url: str,
    allowed_hosts: set[str],
    retries: int,
    max_image_bytes: int,
    watermark_policy: str,
    watermark_texts: list[str],
    workers: int,
    selected_output_format: str,
    title: str,
    chrome_executable: Path,
    output_stem: str,
) -> ProducedPages:
    """Télécharge les pages sélectionnées puis produit l'artefact demandé."""

    images_dir.mkdir(parents=True, exist_ok=True)
    chapter_hosts = set(allowed_hosts)
    chapter_host = (urlparse(page_url).hostname or "").lower()
    if chapter_host:
        chapter_hosts.add(chapter_host)
    trusted_hosts = trusted_selected_resource_hosts(
        pages,
        page_url,
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
        source_url=source_url,
        allowed_hosts=chapter_hosts,
        retries=retries,
        max_image_bytes=max_image_bytes,
        watermark_policy=watermark_policy,
        watermark_texts=watermark_texts,
        workers=workers,
    )
    removed_total = sum(
        int(item.get("watermarks_removed") or 0) for item in results
    )
    quality = (
        "SVG source preserved except exact watermark text; no resize"
        if removed_total
        else "original page bytes preserved; no resize"
    )
    if missing:
        return ProducedPages(
            artifact=None,
            pages=results,
            missing=missing,
            watermarks_removed=removed_total,
            quality=quality,
            trusted_hosts=trusted_hosts,
        )

    ordered = [images_dir / item["file"] for item in results]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = create_selected_output(
        selected_output_format,
        ordered,
        artifact_dir,
        title,
        chrome_executable=chrome_executable,
        output_stem=output_stem,
    )
    if (
        selected_output_format in {"cbz", "cbr"}
        and ordered
        and all(path.suffix.lower() == ".svg" for path in ordered)
    ):
        quality = (
            "SVG source rendered as lossless PNG at its native viewBox size "
            "for CBZ/CBR reader compatibility"
        )
    return ProducedPages(
        artifact=artifact,
        pages=results,
        missing=[],
        watermarks_removed=removed_total,
        quality=quality,
        trusted_hosts=trusted_hosts,
    )
