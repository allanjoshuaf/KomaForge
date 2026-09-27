"""Stable metadata for KomaForge sources and reusable reader families."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{field_name} must be a non-empty tuple")
    for value in values:
        _require_text(value, field_name)


class SourceStatus(str, Enum):
    """Operational confidence of a source shipped with KomaForge."""

    VALIDATED = "validated"
    DEGRADED = "degraded"
    EXPERIMENTAL = "experimental"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Versioned facts about one adapter, separate from runtime matching."""

    languages: tuple[str, ...]
    domains: tuple[str, ...]
    version: str
    status: SourceStatus
    status_reason: str
    family_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text_tuple(self.languages, "source language")
        _require_text_tuple(self.domains, "source domain")
        _require_text(self.version, "source version")
        if not isinstance(self.status, SourceStatus):
            raise ValueError("status must be a SourceStatus")
        _require_text(self.status_reason, "status reason")
        if not isinstance(self.family_ids, tuple):
            raise ValueError("family_ids must be a tuple")
        for family_id in self.family_ids:
            _require_text(family_id, "family id")


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
    )
