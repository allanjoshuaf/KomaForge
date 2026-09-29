"""Source adapter contracts and registry."""

from .calameo import CalameoSource
from .catalog import (
    BUILTIN_READER_FAMILIES,
    BUILTIN_SOURCE_CANDIDATES,
    ReaderFamily,
    SourceAccess,
    SourceCandidate,
    SourceIntegration,
    SourceMetadata,
    SourceStatus,
    candidate_for_url,
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
from .mangadex import MangaDexSource
from .mgu_russian import MguRussianStoreSource
from .registry import (
    AmbiguousSourceError,
    DuplicateSourceError,
    SourceMatchError,
    SourceRegistry,
    SourceResolution,
)


def build_default_registry() -> SourceRegistry:
    """Build the registry of specialized sources shipped with KomaForge."""

    return SourceRegistry(
        (
            CalameoSource(),
            MangaUpSource(),
            EBooksSource(),
            MangaDexSource(),
            MguRussianStoreSource(),
        )
    )

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
    "MangaDexSource",
    "MguRussianStoreSource",
    "ReaderFamily",
    "ResourceSet",
    "SearchCapability",
    "SearchPage",
    "SourceAdapter",
    "SourceAccess",
    "SourceCandidate",
    "SourceIntegration",
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
    "candidate_for_url",
    "metadata_for",
]
