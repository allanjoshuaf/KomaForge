"""Source adapter contracts and registry."""

from .calameo import CalameoSource
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
from .generic import GenericWebSource
from .registry import (
    AmbiguousSourceError,
    DuplicateSourceError,
    SourceMatchError,
    SourceRegistry,
    SourceResolution,
)


def build_default_registry() -> SourceRegistry:
    """Build the registry of specialized sources shipped with KomaForge."""

    return SourceRegistry((CalameoSource(),))

__all__ = [
    "AmbiguousSourceError",
    "BrowseCapability",
    "CalameoSource",
    "DuplicateSourceError",
    "GenericWebSource",
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
    "build_default_registry",
]
