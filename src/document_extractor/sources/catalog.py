"""Stable metadata for KomaForge sources and reusable reader families."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from urllib.parse import urlparse


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{field_name} must be a non-empty tuple")
    for value in values:
        _require_text(value, field_name)


def _require_iso_date(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _require_text(value, field_name)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


class SourceStatus(str, Enum):
    """Compatibility confidence backed by the current regression baseline."""

    VALIDATED = "validated"
    DEGRADED = "degraded"
    EXPERIMENTAL = "experimental"
    OFFLINE = "offline"


class SourceIntegration(str, Enum):
    """How a source is connected to the extraction core."""

    SPECIALIZED = "specialized"
    GENERIC = "generic"


class SourceAccess(str, Enum):
    """Access conditions observed independently from compatibility."""

    FULL = "full"
    SOURCE_LIMITED = "source_limited"
    SESSION_DEPENDENT = "session_dependent"
    VARIABLE = "variable"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Versioned facts about one adapter, separate from runtime matching."""

    languages: tuple[str, ...]
    domains: tuple[str, ...]
    version: str
    status: SourceStatus
    status_reason: str
    integration: SourceIntegration = SourceIntegration.SPECIALIZED
    access: SourceAccess = SourceAccess.FULL
    family_ids: tuple[str, ...] = ()
    last_verified: str | None = None

    def __post_init__(self) -> None:
        _require_text_tuple(self.languages, "source language")
        _require_text_tuple(self.domains, "source domain")
        _require_text(self.version, "source version")
        if not isinstance(self.status, SourceStatus):
            raise ValueError("status must be a SourceStatus")
        _require_text(self.status_reason, "status reason")
        if not isinstance(self.integration, SourceIntegration):
            raise ValueError("integration must be a SourceIntegration")
        if not isinstance(self.access, SourceAccess):
            raise ValueError("access must be a SourceAccess")
        if not isinstance(self.family_ids, tuple):
            raise ValueError("family_ids must be a tuple")
        for family_id in self.family_ids:
            _require_text(family_id, "family id")
        _require_iso_date(self.last_verified, "last_verified")


@dataclass(frozen=True, slots=True)
class ReaderFamily:
    """A reusable extraction strategy observed in supported readers."""

    id: str
    name: str
    status: SourceStatus
    description: str

    def __post_init__(self) -> None:
        _require_text(self.id, "family id")
        _require_text(self.name, "family name")
        if not isinstance(self.status, SourceStatus):
            raise ValueError("status must be a SourceStatus")
        _require_text(self.description, "family description")


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    """Known site handled by a generic family, without a dedicated adapter."""

    id: str
    name: str
    languages: tuple[str, ...]
    domains: tuple[str, ...]
    status: SourceStatus
    status_reason: str
    adapter_id: str
    family_ids: tuple[str, ...]
    integration: SourceIntegration = SourceIntegration.GENERIC
    access: SourceAccess = SourceAccess.FULL
    last_verified: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "candidate id")
        _require_text(self.name, "candidate name")
        _require_text_tuple(self.languages, "candidate language")
        _require_text_tuple(self.domains, "candidate domain")
        if not isinstance(self.status, SourceStatus):
            raise ValueError("status must be a SourceStatus")
        _require_text(self.status_reason, "status reason")
        _require_text(self.adapter_id, "adapter id")
        _require_text_tuple(self.family_ids, "family id")
        if not isinstance(self.integration, SourceIntegration):
            raise ValueError("integration must be a SourceIntegration")
        if not isinstance(self.access, SourceAccess):
            raise ValueError("access must be a SourceAccess")
        _require_iso_date(self.last_verified, "last_verified")


BUILTIN_READER_FAMILIES = (
    ReaderFamily(
        id="paginated-images",
        name="Lecteur d'images paginé",
        status=SourceStatus.VALIDATED,
        description="Séquence numérotée d'images avec navigation page par page.",
    ),
    ReaderFamily(
        id="vertical-images",
        name="Lecteur d'images vertical",
        status=SourceStatus.VALIDATED,
        description="Séquence d'images chargée progressivement par défilement.",
    ),
    ReaderFamily(
        id="direct-document",
        name="Document direct",
        status=SourceStatus.VALIDATED,
        description="PDF ou EPUB observé et validé dans la session du navigateur.",
    ),
    ReaderFamily(
        id="selectable-parts",
        name="Parties sélectionnables",
        status=SourceStatus.EXPERIMENTAL,
        description="Volumes, chapitres ou sections exposés par un contrôle du lecteur.",
    ),
)


BUILTIN_SOURCE_CANDIDATES = (
    SourceCandidate(
        id="sushiscan",
        name="SushiScan",
        languages=("fr",),
        domains=("sushiscan.net",),
        status=SourceStatus.VALIDATED,
        status_reason="241/241 live baseline validated through the generic adapter",
        adapter_id="generic-web",
        family_ids=("vertical-images",),
        last_verified="2026-09-28",
    ),
    SourceCandidate(
        id="mangareader-pro",
        name="MangaReader.pro",
        languages=("en",),
        domains=("mangareader.pro", "www.mangareader.pro"),
        status=SourceStatus.VALIDATED,
        status_reason="complete live baseline validated through the generic adapter",
        adapter_id="generic-web",
        family_ids=("vertical-images",),
        last_verified="2026-09-28",
    ),
    SourceCandidate(
        id="scribd",
        name="Scribd",
        languages=("mul",),
        domains=("scribd.com", "www.scribd.com", "fr.scribd.com", "ru.scribd.com"),
        status=SourceStatus.VALIDATED,
        status_reason=(
            "231/231 indexed reader containers validated through the generic adapter"
        ),
        adapter_id="generic-web",
        family_ids=("paginated-images",),
        access=SourceAccess.VARIABLE,
        last_verified="2026-09-30",
    ),
)


def candidate_for_url(url: str) -> SourceCandidate | None:
    """Return a tested generic site without promoting it to a dedicated adapter."""

    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    for candidate in BUILTIN_SOURCE_CANDIDATES:
        if any(
            host == domain.casefold().rstrip(".")
            or host.endswith(f".{domain.casefold().rstrip('.')}")
            for domain in candidate.domains
        ):
            return candidate
    return None


def metadata_for(adapter: object) -> SourceMetadata:
    """Return declared metadata or a safe status for an external adapter."""

    metadata = getattr(adapter, "metadata", None)
    if isinstance(metadata, SourceMetadata):
        return metadata
    return SourceMetadata(
        languages=("und",),
        domains=("undeclared",),
        version="unversioned",
        status=SourceStatus.EXPERIMENTAL,
        status_reason="metadata not declared by this adapter",
        integration=SourceIntegration.GENERIC,
        access=SourceAccess.VARIABLE,
    )
