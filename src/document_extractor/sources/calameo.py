"""Normalized adapter for authorized Calameo publications."""

from __future__ import annotations

import hashlib

from ..models import (
    Confidence,
    Coverage,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
)
from ..paths import canonical_source_identity
from ..providers import (
    ProviderDiscovery,
    _calameo_book_code,
    discover_provider,
)
from .catalog import SourceMetadata, SourceStatus
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceReference,
    SourceSession,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _confidence(value: str | None) -> Confidence:
    normalized = (value or "").casefold()
    if normalized in {"élevée", "elevee", "high"}:
        return Confidence.HIGH
    if normalized in {"faible", "low"}:
        return Confidence.LOW
    return Confidence.MEDIUM


def publication_from_provider(
    discovery: ProviderDiscovery,
    source_url: str,
) -> Publication:
    """Convert the proven legacy provider result without changing its resources."""

    canonical = canonical_source_identity(source_url)
    work_id = _stable_id("work", canonical)
    publication_id = _stable_id("publication", canonical)
    parts: list[Part] = []
    total_available = 0
    total_expected = 0
    all_expected = True
    evidence: list[str] = []
    confidence = Confidence.MEDIUM

    for chapter in discovery.chapters:
        expected = chapter.expected.value if chapter.expected else None
        if expected is None:
            all_expected = False
        else:
            total_expected += expected
            evidence.append(chapter.expected.source)
            confidence = max(
                confidence,
                _confidence(chapter.expected.confidence),
                key=lambda item: {
                    Confidence.LOW: 1,
                    Confidence.MEDIUM: 2,
                    Confidence.HIGH: 3,
                }[item],
            )
        resources = tuple(
            Resource(
                id=_stable_id(
                    "resource",
                    f"{canonical}:{chapter.index}:{page.get('page', position)}:{page['url']}",
                ),
                kind=ResourceKind.SVG,
                locator=str(page["url"]),
                position=position,
                metadata={
                    key: value
                    for key, value in page.items()
                    if key not in {"page", "url"}
                },
            )
            for position, page in enumerate(chapter.pages, start=1)
        )
        total_available += len(resources)
        coverage = Coverage.from_counts(
            len(resources),
            expected,
            unit="resources",
            evidence=chapter.expected.source if chapter.expected else "Calameo adapter",
            confidence=_confidence(
                chapter.expected.confidence if chapter.expected else None
            ),
        )
        parts.append(
            Part(
                id=_stable_id(
                    "part",
                    f"{canonical}:{chapter.index}:{chapter.number}",
                ),
                kind=(
                    PartKind.DOCUMENT
                    if discovery.publication_type == "book"
                    else PartKind.CHAPTER
                ),
                title=chapter.title,
                position=chapter.index,
                number=chapter.number,
                source_url=chapter.source_url or source_url,
                resources=resources,
                coverage=coverage,
            )
        )

    publication_coverage = Coverage.from_counts(
        total_available,
        total_expected if all_expected else None,
        unit="resources",
        evidence=", ".join(dict.fromkeys(evidence)) if evidence else "Calameo adapter",
        confidence=confidence,
    )
    return Publication(
        id=publication_id,
        work_id=work_id,
        source_id=CalameoSource.id,
        title=discovery.title,
        source_url=source_url,
        parts=tuple(parts),
        coverage=publication_coverage,
        metadata={
            "provider": discovery.name,
            "publication_type": discovery.publication_type,
            "allowed_hosts": sorted(discovery.allowed_hosts),
        },
    )


class CalameoSource:
    id = "calameo"
    name = "Calameo"
    metadata = SourceMetadata(
        languages=("mul",),
        domains=("calameo.com", "www.calameo.com"),
        version="1",
        status=SourceStatus.VALIDATED,
        status_reason="publication metadata and page coverage are regression-tested",
        family_ids=("paginated-images",),
        last_verified="2026-09-27",
    )

    def match(self, url: str, context: MatchContext) -> MatchResult:
        if _calameo_book_code(url) is None:
            return MatchResult.no_match("not a Calameo /read/ URL")
        return MatchResult.recognized(
            "official Calameo publication URL",
            confidence=Confidence.HIGH,
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
        if session.browser_context is None or session.page is None:
            raise RuntimeError("CalameoSource requires a browser context and page")
        source_url = reference.url or reference.value
        discovery = discover_provider(
            session.browser_context,
            session.page,
            source_url,
        )
        if discovery is None:
            raise RuntimeError(
                "CalameoSource recognized the URL but could not inspect the publication"
            )
        return publication_from_provider(discovery, source_url)

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
        if publication.source_id != self.id:
            raise ValueError(
                f"publication belongs to {publication.source_id!r}, not {self.id!r}"
            )
        return publication.parts

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        if part.coverage is None:
            raise RuntimeError("Calameo part has no coverage evidence")
        return ResourceSet(part.resources, part.coverage)
