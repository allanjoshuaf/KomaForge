"""Source adapter contracts and registry."""

from .contracts import (
    BrowseCapability,
    MatchContext,
    MatchResult,
    ResourceSet,
    SearchCapability,
    SearchPage,
    SourceAdapter,
    SourceReference,
    SourceSession,
    UpdateCapability,
    UpdateResult,
)
from .registry import (
    AmbiguousSourceError,
    DuplicateSourceError,
    SourceMatchError,
    SourceRegistry,
    SourceResolution,
)

__all__ = [
    "AmbiguousSourceError",
    "BrowseCapability",
    "DuplicateSourceError",
    "MatchContext",
    "MatchResult",
    "ResourceSet",
    "SearchCapability",
    "SearchPage",
    "SourceAdapter",
    "SourceMatchError",
    "SourceReference",
    "SourceRegistry",
    "SourceResolution",
    "SourceSession",
    "UpdateCapability",
    "UpdateResult",
]
