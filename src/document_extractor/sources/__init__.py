"""Source adapter contracts and registry."""

from .calameo import CalameoSource
from .catalog import (
    BUILTIN_READER_FAMILIES,
    BUILTIN_SOURCE_CANDIDATES,
    ReaderFamily,
    SourceCandidate,
    SourceMetadata,
    SourceStatus,
    metadata_for,
)
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
    "BUILTIN_READER_FAMILIES",
    "BUILTIN_SOURCE_CANDIDATES",
    "BrowseCapability",
    "CalameoSource",
    "DuplicateSourceError",
    "EBooksSource",
    "GenericWebSource",
    "MatchContext",
    "MatchResult",
    "MangaUpSource",
    "ReaderFamily",
    "ResourceSet",
    "SearchCapability",
    "SearchPage",
    "SourceAdapter",
    "SourceCandidate",
    "SourceMatchError",
    "SourceMetadata",
    "SourceReference",
    "SourceRegistry",
    "SourceResolution",
    "SourceSession",
    "SourceStatus",
    "UpdateCapability",
    "UpdateResult",
    "build_default_registry",
    "metadata_for",
]
