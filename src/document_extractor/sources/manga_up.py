"""Normalized adapter for Manga UP's public publication catalog."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

from ..detection import StructuredChapterCatalog, discover_manga_up_catalog
from ..models import (
    Confidence,
    Coverage,
    Part,
    PartKind,
    Publication,
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
from .generic import GenericWebSource
from ..updates import compare_part_updates


_MANGA_PATH = re.compile(
    r"^(?P<base>(?:/[a-z]{2})?/manga/[0-9]+)(?:/[0-9]+)?/*$",
    re.IGNORECASE,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _work_url(value: str) -> str | None:
    parsed = urlparse(value)
    if (parsed.hostname or "").casefold() != "global.manga-up.com":
        return None
    match = _MANGA_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    return urlunparse(("https", parsed.netloc, match.group("base"), "", "", ""))


def publication_from_catalog(
    catalog: StructuredChapterCatalog,
    *,
    source_url: str,
    title: str,
) -> Publication:
    canonical = canonical_source_identity(source_url)
    work_id = _stable_id("work", canonical)
    parts = tuple(
        Part(
            id=_stable_id("part", canonical_source_identity(chapter.url)),
            kind=PartKind.SEGMENT,
            title=chapter.title,
            position=chapter.index,
            number=chapter.number,
            source_url=chapter.url,
            coverage=Coverage.from_counts(0, None, unit="resources"),
            metadata={"catalog_source": catalog.source},
        )
        for chapter in catalog.chapters
    )
    coverage = Coverage.from_counts(
        catalog.accessible_count,
        catalog.total_count,
        unit="parts",
        evidence=catalog.source,
        confidence=Confidence.HIGH,
        source_limited=catalog.access_limited,
        detail=(
            "The public source exposes only a subset of the announced catalog."
            if catalog.access_limited
            else None
        ),
    )
    return Publication(
        id=_stable_id("publication", canonical),
        work_id=work_id,
        source_id=MangaUpSource.id,
        title=title,
        source_url=source_url,
        parts=parts,
        coverage=coverage,
        metadata={
            "catalog_source": catalog.source,
            "access_limited": catalog.access_limited,
        },
    )


class MangaUpSource:
    id = "manga-up"
    name = "Manga UP"
    metadata = SourceMetadata(
        languages=("en",),
        domains=("global.manga-up.com",),
        version="1",
        status=SourceStatus.VALIDATED,
        status_reason="catalog discovery and source-limited coverage are regression-tested",
        family_ids=("paginated-images",),
    )

    def __init__(self) -> None:
        self._generic_resources = GenericWebSource()

    def match(self, url: str, context: MatchContext) -> MatchResult:
        if _work_url(url) is None:
            return MatchResult.no_match("not a Manga UP publication URL")
        return MatchResult.recognized(
            "official Manga UP publication URL",
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
        if session.page is None:
            raise RuntimeError("MangaUpSource requires a prepared browser page")
        source_url = _work_url(reference.url or reference.value)
        if source_url is None:
            raise ValueError("reference is not a Manga UP publication URL")
        catalog = discover_manga_up_catalog(session.page, source_url)
        if catalog is None:
            raise RuntimeError(
                "MangaUpSource recognized the URL but found no public catalog "
                "on the prepared publication page"
            )
        title = clean_publication_title(str(session.page.title() or ""))
        if not title:
            title = "Manga UP publication"
        return publication_from_catalog(
            catalog,
            source_url=source_url,
            title=title,
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
        return publication.parts

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        return self._generic_resources.get_resources(part, session)

    def check_updates(
        self,
        publication: Publication,
        known_parts: tuple[Part, ...],
        session: SourceSession,
    ) -> UpdateResult:
        if publication.source_id != self.id:
            raise ValueError(
                f"publication belongs to {publication.source_id!r}, not {self.id!r}"
            )
        return compare_part_updates(publication, known_parts, publication.parts)
