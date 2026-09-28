"""Generic URL fallback backed by KomaForge's existing detection primitives."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from ..detection import (
    ExpectedCount,
    activate_reader_gate,
    activate_reading_mode,
    detect_expected_count,
    discover_pages,
    hydrate_lazy_content,
    wait_for_reader_readiness,
)
from ..models import (
    Confidence,
    Coverage,
    Part,
    Publication,
    Resource,
    ResourceKind,
)
from ..paths import canonical_source_identity, clean_publication_title
from ..part_families import discover_part_candidates
from .catalog import SourceAccess, SourceIntegration, SourceMetadata, SourceStatus
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
        integration=SourceIntegration.GENERIC,
        access=SourceAccess.VARIABLE,
        family_ids=(
            "paginated-images",
            "vertical-images",
            "direct-document",
            "selectable-parts",
        ),
        last_verified="2026-09-28",
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
        discovery = discover_part_candidates(
            page,
            publication,
            session.options,
        )
        return tuple(
            Part(
                id=_stable_id("part", candidate.identity),
                kind=candidate.kind,
                title=candidate.title,
                position=candidate.position,
                number=candidate.number,
                source_url=candidate.source_url,
                coverage=Coverage.from_counts(0, None, unit="resources"),
                metadata=candidate.metadata,
            )
            for candidate in discovery.candidates
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
        if expected is not None and len(resources) > expected:
            try:
                indices = sorted(int(item["document_index"]) for item in pages)
            except (KeyError, TypeError, ValueError):
                indices = []
            continuous = indices in (
                list(range(0, len(pages))),
                list(range(1, len(pages) + 1)),
            )
            if continuous and expected_info and expected_info.confidence != "élevée":
                expected = len(resources)
                expected_info = ExpectedCount(
                    expected,
                    "continuous data-index sequence",
                    "élevée",
                )
            else:
                raise RuntimeError(
                    f"source coverage is contradictory: {len(resources)}/{expected}"
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
