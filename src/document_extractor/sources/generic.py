"""Generic URL fallback backed by KomaForge's existing detection primitives."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from ..detection import (
    ExpectedCount,
    activate_reader_gate,
    activate_reading_mode,
    detect_expected_count,
    discover_chapters,
    discover_pages,
    discover_selectable_parts,
    hydrate_lazy_content,
    looks_like_chapter_url,
    wait_for_reader_readiness,
)
from ..models import (
    Confidence,
    Coverage,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
)
from ..paths import canonical_source_identity, clean_publication_title
from .catalog import SourceMetadata, SourceStatus
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceReference,
    SourceSession,
    UpdateResult,
)
from ..updates import compare_part_updates


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _page_from_session(session: SourceSession):
    if session.page is None:
        raise RuntimeError("GenericWebSource requires a prepared browser page")
    return session.page


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


def _resource_kind(page: dict) -> ResourceKind:
    content_type = str(page.get("_embedded_content_type") or "").casefold()
    path = urlparse(str(page.get("url") or "")).path.casefold()
    if "svg" in content_type or path.endswith((".svg", ".svgz")):
        return ResourceKind.SVG
    return ResourceKind.IMAGE


class GenericWebSource:
    """Fallback source for an already prepared browser session.

    Core remains responsible for navigation, access checks, direct PDF/EPUB
    response capture, downloads, and output formats.  This adapter only turns the
    generic page/chapter detectors into normalized domain models.
    """

    id = "generic-web"
    name = "Generic Web"
    metadata = SourceMetadata(
        languages=("mul",),
        domains=("*",),
        version="1",
        status=SourceStatus.EXPERIMENTAL,
        status_reason="coverage depends on the structure exposed by each unknown site",
        family_ids=(
            "paginated-images",
            "vertical-images",
            "direct-document",
            "selectable-parts",
        ),
        last_verified="2026-09-27",
    )

    def match(self, url: str, context: MatchContext) -> MatchResult:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return MatchResult.no_match("not an HTTP(S) publication URL")
        return MatchResult.recognized(
            "generic HTTP(S) fallback",
            confidence=Confidence.LOW,
        )

    def get_publication(
        self,
        reference: SourceReference,
        session: SourceSession,
    ) -> Publication:
        if reference.source_id != self.id:
            raise ValueError(
                f"reference belongs to {reference.source_id!r}, not {self.id!r}"
            )
        page = _page_from_session(session)
        source_url = reference.url or str(getattr(page, "url", "") or reference.value)
        canonical = canonical_source_identity(source_url)
        raw_title = str(page.title() or "").strip()
        title = clean_publication_title(raw_title) or urlparse(source_url).hostname or "Publication"
        work_id = _stable_id("work", canonical)
        return Publication(
            id=_stable_id("publication", canonical),
            work_id=work_id,
            source_id=self.id,
            title=title,
            source_url=source_url,
            metadata={"reference": reference.value},
        )

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
        if publication.source_id != self.id:
            raise ValueError(
                f"publication belongs to {publication.source_id!r}, not {self.id!r}"
            )
        page = _page_from_session(session)
        scope = str(session.options.get("scope") or "auto")
        minimum_chapters = int(session.options.get("minimum_chapters") or 3)
        chapter_links = []
        if scope != "document" and (
            scope == "work" or not looks_like_chapter_url(publication.source_url)
        ):
            chapter_links = discover_chapters(
                page,
                publication.source_url,
                minimum=2 if scope == "work" else minimum_chapters,
            )
        if chapter_links:
            return tuple(
                Part(
                    id=_stable_id("part", canonical_source_identity(chapter.url)),
                    kind=PartKind.CHAPTER,
                    title=chapter.title,
                    position=chapter.index,
                    number=chapter.number,
                    source_url=chapter.url,
                    coverage=Coverage.from_counts(0, None, unit="resources"),
                )
                for chapter in chapter_links
            )

        selectable_parts = []
        if scope != "document":
            selectable_parts = discover_selectable_parts(
                page,
                minimum=2,
                wait_timeout_ms=int(session.options.get("part_wait_timeout_ms") or 0),
            )
        if selectable_parts:
            return tuple(
                Part(
                    id=_stable_id(
                        "part",
                        f"{publication.id}:{item.kind}:{item.number}:{item.value}",
                    ),
                    kind=_part_kind(item.kind),
                    title=item.title,
                    position=item.index,
                    number=item.number,
                    source_url=publication.source_url,
                    coverage=Coverage.from_counts(0, None, unit="resources"),
                    metadata={
                        "selection_selector": item.selector,
                        "selection_value": item.value,
                    },
                )
                for item in selectable_parts
            )

        number_match = re.search(
            r"(?i)(?:chapter|chapitre|ch\.?)\s*[-_/#.:]*([0-9]+(?:[.,][0-9]+)?)",
            publication.source_url,
        )
        number = number_match.group(1).replace(",", ".") if number_match else None
        return (
            Part(
                id=_stable_id("part", canonical_source_identity(publication.source_url)),
                kind=PartKind.CHAPTER if number else PartKind.DOCUMENT,
                title=publication.title if number is None else f"Chapter {number}",
                position=1,
                number=number,
                source_url=publication.source_url,
                coverage=Coverage.from_counts(0, None, unit="resources"),
            ),
        )

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        page = _page_from_session(session)
        current_url = str(getattr(page, "url", "") or "")
        if part.source_url != current_url and not part.metadata.get("selection_selector"):
            raise RuntimeError(
                "Core must navigate the prepared browser page to the part URL "
                "before GenericWebSource.get_resources()"
            )

        selector = part.metadata.get("selection_selector")
        value = part.metadata.get("selection_value")
        if selector and value is not None:
            page.locator(str(selector)).select_option(str(value))

        if bool(session.options.get("activate_reader", True)):
            activate_reader_gate(page)
            wait_for_reader_readiness(page)
            activate_reading_mode(
                page,
                session.options.get("reading_mode_selector"),
                session.options.get("reading_mode_value"),
                True,
            )

        expected_option = session.options.get("expected")
        if expected_option is not None:
            expected_info = ExpectedCount(int(expected_option), "adapter option", "élevée")
        else:
            expected_info = detect_expected_count(page)
        expected = expected_info.value if expected_info else None

        hydrate_lazy_content(page, expected)
        pages, selector_used = discover_pages(
            page,
            session.options.get("selector"),
            expected,
        )
        resources = tuple(
            Resource(
                id=_stable_id(
                    "resource",
                    f"{part.id}:{item.get('page', position)}:{item.get('url', '')}",
                ),
                kind=_resource_kind(item),
                locator=str(item["url"]),
                position=position,
                metadata={
                    key: value
                    for key, value in item.items()
                    if key not in {"page", "url"}
                },
            )
            for position, item in enumerate(pages, start=1)
        )
        coverage = Coverage.from_counts(
            len(resources),
            expected,
            unit="resources",
            evidence=expected_info.source if expected_info else selector_used,
            confidence=(
                Confidence.HIGH
                if expected_info and expected_info.confidence == "élevée"
                else Confidence.MEDIUM
            ),
        )
        return ResourceSet(resources, coverage)

    def check_updates(
        self,
        publication: Publication,
        known_parts: tuple[Part, ...],
        session: SourceSession,
    ) -> UpdateResult:
        current_parts = self.get_parts(publication, session)
        return compare_part_updates(publication, known_parts, current_parts)
