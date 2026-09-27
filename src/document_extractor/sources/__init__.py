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
from .ebooks import EBooksSource
from .generic import GenericWebSource
from .manga_up import MangaUpSource
from .registry import (
    AmbiguousSourceError,
    DuplicateSourceError,
    SourceMatchError,
    SourceRegistry,
    SourceResolution,
)


def build_default_registry() -> SourceRegistry:
    """Build the registry of specialized sources shipped with KomaForge."""

    return SourceRegistry((CalameoSource(), MangaUpSource(), EBooksSource()))

__all__ = [
    "AmbiguousSourceError",
    "BrowseCapability",
    "CalameoSource",
    "DuplicateSourceError",
    "EBooksSource",
    "GenericWebSource",
    "MatchContext",
    "MatchResult",
    "MangaUpSource",
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
