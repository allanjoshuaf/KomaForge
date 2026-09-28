"""Reusable reader-resource strategies shared by source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import detection


@dataclass(frozen=True, slots=True)
class ReaderResourceMatch:
    """Raw resources selected by one known reader family."""

    family_id: str
    strategy_id: str
    items: list[dict]
    evidence: str


class ReaderResourceStrategy(Protocol):
    """Optional strategy used by the generic source in deterministic order."""

    family_id: str
    strategy_id: str

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None: ...


class VirtualBlobStrategy:
    family_id = "vertical-images"
    strategy_id = "virtual-blob"

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None:
        del expected
        items = detection.collect_virtual_blob_reader_candidates(page)
        if not items:
            return None
        return ReaderResourceMatch(
            self.family_id,
            self.strategy_id,
            items,
            "lecteur virtualisé à pages Blob",
        )


class ChapterManifestStrategy:
    family_id = "vertical-images"
    strategy_id = "chapter-manifest"

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None:
        del expected
        items = detection.collect_chapter_reader_manifest(page)
        if not items:
            return None
        return ReaderResourceMatch(
            self.family_id,
            self.strategy_id,
            items,
            "manifeste du lecteur ChapterReader",
        )


class PaginatedImageStrategy:
    family_id = "paginated-images"
    strategy_id = "paginated-images"

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None:
        del expected
        items = detection.collect_paginated_reader_candidates(page)
        if not items:
            return None
        return ReaderResourceMatch(
            self.family_id,
            self.strategy_id,
            detection._deduplicate(items),
            "lecteur paginé ChapterReader",
        )


class DocumentImageStrategy:
    family_id = "vertical-images"
    strategy_id = "document-images"

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None:
        del expected
        selector = "img[data-document-page]"
        if not page.locator(selector).count():
            return None
        items = detection._deduplicate(
            detection.collect_image_candidates(page, selector)
        )
        return ReaderResourceMatch(
            self.family_id,
            self.strategy_id,
            items,
            selector,
        )


class GroupedImageStrategy:
    family_id = "vertical-images"
    strategy_id = "grouped-images"

    def detect(self, page, expected: int | None) -> ReaderResourceMatch | None:
        candidates = detection.collect_image_candidates(page, "img")
        try:
            items, evidence = detection._auto_group(candidates, expected)
        except RuntimeError as exc:
            surfaces = detection.inspect_render_surfaces(page)
            if (
                surfaces["canvas_count"]
                or surfaces["iframe_count"]
                or surfaces["reader_hint"]
            ):
                count = surfaces.get("accessible_page_count")
                count_text = (
                    f", {count} emplacement(s) accessible(s) annoncé(s)"
                    if count
                    else ""
                )
                raise RuntimeError(
                    "Lecteur canvas/PDF détecté "
                    f"({surfaces['canvas_count']} canvas, "
                    f"{surfaces['iframe_count']} iframe(s){count_text}). "
                    "Les pages originales ne sont pas exposées comme images : "
                    "extraction annulée pour éviter des logos ou des captures "
                    "basse qualité."
                ) from exc
            raise
        return ReaderResourceMatch(
            self.family_id,
            self.strategy_id,
            items,
            evidence,
        )


BUILTIN_RESOURCE_STRATEGIES: tuple[ReaderResourceStrategy, ...] = (
    VirtualBlobStrategy(),
    ChapterManifestStrategy(),
    PaginatedImageStrategy(),
    DocumentImageStrategy(),
    GroupedImageStrategy(),
)


def resolve_reader_resources(
    page,
    explicit_selector: str | None,
    expected: int | None,
) -> ReaderResourceMatch:
    """Select one reader strategy without mixing candidates from families."""

    manifest_pages = detection.pages_from_manifest(page)
    if manifest_pages:
        return ReaderResourceMatch(
            "vertical-images",
            "html-manifest",
            manifest_pages,
            "html-manifest",
        )

    selector = detection.normalize_selector_input(explicit_selector)
    if selector:
        return ReaderResourceMatch(
            "vertical-images",
            "explicit-selector",
            detection._deduplicate(
                detection.collect_image_candidates(page, selector)
            ),
            selector,
        )

    for strategy in BUILTIN_RESOURCE_STRATEGIES:
        match = strategy.detect(page, expected)
        if match is not None:
            return match
    raise RuntimeError("no reader-resource strategy produced a result")


def discover_resource_pages(
    page,
    explicit_selector: str | None,
    expected: int | None,
) -> tuple[list[dict], str]:
    """Return normalized pages while preserving the historical Core API."""

    match = resolve_reader_resources(page, explicit_selector, expected)
    if match.strategy_id == "html-manifest":
        return match.items, match.evidence
    pages = [
        {
            "page": position,
            "url": item["url"],
            "source": match.evidence,
            **{
                key: value
                for key, value in item.items()
                if key.startswith("_embedded_")
            },
            **(
                {"document_index": item["dataIndex"]}
                if item.get("dataIndex") is not None
                else {}
            ),
        }
        for position, item in enumerate(match.items, start=1)
    ]
    return pages, match.evidence
