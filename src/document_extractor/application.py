"""Application-level source routing without extraction side effects."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Publication, UpdateResult
from .paths import canonical_source_identity
from .sources import (
    GenericWebSource,
    MatchContext,
    MatchResult,
    SourceAdapter,
    SourceRegistry,
    SourceSession,
    UpdateCapability,
    build_default_registry,
)


@dataclass(frozen=True, slots=True)
class SourceRoute:
    adapter: SourceAdapter
    match: MatchResult
    specialized: bool


def resolve_source(
    url: str,
    *,
    context: MatchContext | None = None,
    registry: SourceRegistry | None = None,
    generic: GenericWebSource | None = None,
) -> SourceRoute:
    """Select one source once; never fall back after a specialized match."""

    active_registry = registry or build_default_registry()
    resolution = active_registry.resolve(url, context)
    if resolution is not None:
        return SourceRoute(resolution.adapter, resolution.match, True)

    fallback = generic or GenericWebSource()
    match = fallback.match(url, context or MatchContext())
    if not match.matched:
        raise ValueError(f"no KomaForge source accepts URL: {url!r}")
    return SourceRoute(fallback, match, False)


def plan_publication_updates(
    known: Publication,
    current: Publication,
    session: SourceSession,
    *,
    adapter: SourceAdapter | None = None,
) -> UpdateResult:
    """Compare a fresh source publication with one reconstructed from the library."""

    if known.source_id != current.source_id:
        raise ValueError("known and current publications use different sources")
    if canonical_source_identity(known.source_url) != canonical_source_identity(
        current.source_url
    ):
        raise ValueError("known and current publications have different identities")
    active_adapter = adapter or resolve_source(known.source_url).adapter
    if active_adapter.id != known.source_id:
        raise ValueError("selected adapter does not own the known publication")
    if not isinstance(active_adapter, UpdateCapability):
        raise NotImplementedError(
            f"source {active_adapter.id!r} does not provide update checks"
        )
    return active_adapter.check_updates(current, known.parts, session)
