"""Deterministic registry for specialized source adapters."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Confidence
from .contracts import MatchContext, MatchResult, SourceAdapter


class DuplicateSourceError(ValueError):
    pass


class SourceMatchError(RuntimeError):
    pass


class AmbiguousSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceResolution:
    adapter: SourceAdapter
    match: MatchResult


_CONFIDENCE_RANK = {
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


class SourceRegistry:
    """Holds specialized sources; the generic fallback lives outside the registry.

    Keeping the fallback outside makes the routing rule explicit: no specialized
    match means the application may invoke GenericWebSource.  A matching adapter
    that later fails remains selected and its error must be reported.
    """

    def __init__(self, adapters: tuple[SourceAdapter, ...] = ()) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        if not isinstance(adapter, SourceAdapter):
            raise TypeError("adapter does not implement SourceAdapter")
        source_id = getattr(adapter, "id", None)
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("adapter id must be a non-empty string")
        if source_id in self._adapters:
            raise DuplicateSourceError(f"source adapter already registered: {source_id}")
        self._adapters[source_id] = adapter

    def all(self) -> tuple[SourceAdapter, ...]:
        return tuple(self._adapters.values())

    def get(self, source_id: str) -> SourceAdapter | None:
        return self._adapters.get(source_id)

    def resolve(
        self,
        url: str,
        context: MatchContext | None = None,
    ) -> SourceResolution | None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        match_context = context or MatchContext()
        matches: list[SourceResolution] = []
        for adapter in self._adapters.values():
            try:
                result = adapter.match(url, match_context)
            except Exception as exc:
                raise SourceMatchError(
                    f"source adapter {adapter.id!r} failed while matching {url!r}: {exc}"
                ) from exc
            if not isinstance(result, MatchResult):
                raise SourceMatchError(
                    f"source adapter {adapter.id!r} returned an invalid MatchResult"
                )
            if result.matched:
                matches.append(SourceResolution(adapter, result))

        if not matches:
            return None
        best_rank = max(_CONFIDENCE_RANK[item.match.confidence] for item in matches)
        best = [
            item
            for item in matches
            if _CONFIDENCE_RANK[item.match.confidence] == best_rank
        ]
        if len(best) > 1:
            source_ids = ", ".join(sorted(item.adapter.id for item in best))
            raise AmbiguousSourceError(
                f"multiple source adapters matched with equal confidence: {source_ids}"
            )
        return best[0]
