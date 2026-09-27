"""Application-level source routing without extraction side effects."""

from __future__ import annotations

from dataclasses import dataclass

from .sources import (
    GenericWebSource,
    MatchContext,
    MatchResult,
    SourceAdapter,
    SourceRegistry,
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
