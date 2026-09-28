"""Reusable strategies for discovering chapters, volumes, and documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from . import detection
from .models import PartKind, Publication
from .paths import canonical_source_identity


def _part_kind(value: str) -> PartKind:
    normalized = value.casefold()
    if normalized == "chapter":
        return PartKind.CHAPTER
    if normalized == "volume":
        return PartKind.VOLUME
    if normalized in {"section", "part", "book", "issue"}:
        return PartKind.SECTION
    if normalized == "segment":
        return PartKind.SEGMENT
    return PartKind.DOCUMENT


@dataclass(frozen=True, slots=True)
class PartCandidate:
    identity: str
    kind: PartKind
    title: str
    position: int
    number: str | None
    source_url: str
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PartDiscovery:
    family_id: str
    strategy_id: str
    candidates: tuple[PartCandidate, ...]


class PartDiscoveryStrategy(Protocol):
    family_id: str
    strategy_id: str

    def discover(
        self,
        page,
        publication: Publication,
        options: Mapping[str, object],
    ) -> PartDiscovery | None: ...


class LinkedChapterStrategy:
    family_id = "selectable-parts"
    strategy_id = "linked-chapters"

    def discover(
        self,
        page,
        publication: Publication,
        options: Mapping[str, object],
    ) -> PartDiscovery | None:
        scope = str(options.get("scope") or "auto")
        if scope == "document" or (
            scope != "work"
            and detection.looks_like_chapter_url(publication.source_url)
        ):
            return None
        minimum_chapters = int(options.get("minimum_chapters") or 3)
        chapters = detection.discover_chapters(
            page,
            publication.source_url,
            minimum=2 if scope == "work" else minimum_chapters,
        )
        if not chapters:
            return None
        return PartDiscovery(
            self.family_id,
            self.strategy_id,
            tuple(
                PartCandidate(
                    identity=canonical_source_identity(chapter.url),
                    kind=PartKind.CHAPTER,
                    title=chapter.title,
                    position=chapter.index,
                    number=chapter.number,
                    source_url=chapter.url,
                    metadata={},
                )
                for chapter in chapters
            ),
        )


class SelectablePartStrategy:
    family_id = "selectable-parts"
    strategy_id = "select-control"

    def discover(
        self,
        page,
        publication: Publication,
        options: Mapping[str, object],
    ) -> PartDiscovery | None:
        if str(options.get("scope") or "auto") == "document":
            return None
        selectable = detection.discover_selectable_parts(
            page,
            minimum=2,
            wait_timeout_ms=int(options.get("part_wait_timeout_ms") or 0),
        )
        if not selectable:
            return None
        return PartDiscovery(
            self.family_id,
            self.strategy_id,
            tuple(
                PartCandidate(
                    identity=(
                        f"{publication.id}:{item.kind}:{item.number}:{item.value}"
                    ),
                    kind=_part_kind(item.kind),
                    title=item.title,
                    position=item.index,
                    number=item.number,
                    source_url=publication.source_url,
                    metadata={
                        "selection_selector": item.selector,
                        "selection_value": item.value,
                    },
                )
                for item in selectable
            ),
        )


class SingleDocumentStrategy:
    family_id = "direct-document"
    strategy_id = "single-document"

    def discover(
        self,
        page,
        publication: Publication,
        options: Mapping[str, object],
    ) -> PartDiscovery | None:
        del page, options
        number_match = re.search(
            r"(?i)(?:chapter|chapitre|ch\.?)\s*[-_/#.:]*([0-9]+(?:[.,][0-9]+)?)",
            publication.source_url,
        )
        number = number_match.group(1).replace(",", ".") if number_match else None
        return PartDiscovery(
            self.family_id,
            self.strategy_id,
            (
                PartCandidate(
                    identity=canonical_source_identity(publication.source_url),
                    kind=PartKind.CHAPTER if number else PartKind.DOCUMENT,
                    title=publication.title if number is None else f"Chapter {number}",
                    position=1,
                    number=number,
                    source_url=publication.source_url,
                    metadata={},
                ),
            ),
        )


BUILTIN_PART_STRATEGIES: tuple[PartDiscoveryStrategy, ...] = (
    LinkedChapterStrategy(),
    SelectablePartStrategy(),
    SingleDocumentStrategy(),
)


def discover_part_candidates(
    page,
    publication: Publication,
    options: Mapping[str, object],
) -> PartDiscovery:
    """Return the first complete part interpretation in deterministic order."""

    for strategy in BUILTIN_PART_STRATEGIES:
        discovery = strategy.discover(page, publication, options)
        if discovery is not None:
            return discovery
    raise RuntimeError("no part-discovery strategy produced a result")
