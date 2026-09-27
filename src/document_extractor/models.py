"""Normalized domain models shared by KomaForge Core, Sources, and Library.

These models describe what a source exposes.  They intentionally do not know how
resources are downloaded, converted, indexed, or displayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class PartKind(str, Enum):
    CHAPTER = "chapter"
    VOLUME = "volume"
    SECTION = "section"
    DOCUMENT = "document"
    SEGMENT = "segment"


class ResourceKind(str, Enum):
    IMAGE = "image"
    SVG = "svg"
    PDF = "pdf"
    EPUB = "epub"
    VIDEO = "video"
    MANIFEST = "manifest"


class CoverageStatus(str, Enum):
    UNKNOWN = "unknown"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    SOURCE_LIMITED = "source_limited"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _metadata_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a mapping")
    return dict(value)


@dataclass(frozen=True, slots=True)
class Coverage:
    """Evidence-backed coverage of one ordered collection.

    ``available`` counts the relevant items actually exposed by the source, not
    every visual candidate seen by the browser.  A known ``expected`` total is
    required before KomaForge may claim complete, incomplete, or source-limited
    coverage.
    """

    status: CoverageStatus
    available: int
    expected: int | None = None
    unit: str = "resources"
    evidence: str | None = None
    confidence: Confidence = Confidence.MEDIUM
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CoverageStatus):
            raise ValueError("status must be a CoverageStatus")
        if not isinstance(self.confidence, Confidence):
            raise ValueError("confidence must be a Confidence")
        if not isinstance(self.available, int) or isinstance(self.available, bool):
            raise ValueError("available must be an integer")
        if self.available < 0:
            raise ValueError("available cannot be negative")
        if self.expected is not None:
            if not isinstance(self.expected, int) or isinstance(self.expected, bool):
                raise ValueError("expected must be an integer or None")
            if self.expected < 0:
                raise ValueError("expected cannot be negative")
            if self.available > self.expected:
                raise ValueError("available cannot exceed expected")
        _require_text(self.unit, "unit")
        if self.evidence is not None:
            _require_text(self.evidence, "evidence")
        if self.detail is not None:
            _require_text(self.detail, "detail")

        if self.status is CoverageStatus.UNKNOWN:
            return
        if self.expected is None:
            raise ValueError(f"{self.status.value} coverage requires an expected total")
        if self.status is CoverageStatus.COMPLETE and self.available != self.expected:
            raise ValueError("complete coverage requires available == expected")
        if self.status in {
            CoverageStatus.INCOMPLETE,
            CoverageStatus.SOURCE_LIMITED,
        } and self.available >= self.expected:
            raise ValueError(
                f"{self.status.value} coverage requires available < expected"
            )

    @property
    def missing(self) -> int | None:
        if self.expected is None:
            return None
        return self.expected - self.available

    @property
    def is_complete(self) -> bool:
        return self.status is CoverageStatus.COMPLETE

    @classmethod
    def from_counts(
        cls,
        available: int,
        expected: int | None,
        *,
        unit: str = "resources",
        evidence: str | None = None,
        confidence: Confidence = Confidence.MEDIUM,
        source_limited: bool = False,
        detail: str | None = None,
    ) -> Coverage:
        if expected is None:
            status = CoverageStatus.UNKNOWN
        elif available == expected:
            status = CoverageStatus.COMPLETE
        elif source_limited:
            status = CoverageStatus.SOURCE_LIMITED
        else:
            status = CoverageStatus.INCOMPLETE
        return cls(
            status=status,
            available=available,
            expected=expected,
            unit=unit,
            evidence=evidence,
            confidence=confidence,
            detail=detail,
        )

    def to_manifest(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "unit": self.unit,
            "available": self.available,
            "expected": self.expected,
            "missing": self.missing,
            "evidence": self.evidence,
            "confidence": self.confidence.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    kind: ResourceKind
    locator: str
    position: int
    media_type: str | None = None
    filename: str | None = None
    sha256: str | None = None
    sensitive_locator: bool = False
    public_locator: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "resource id")
        if not isinstance(self.kind, ResourceKind):
            raise ValueError("kind must be a ResourceKind")
        _require_text(self.locator, "resource locator")
        if not isinstance(self.position, int) or isinstance(self.position, bool):
            raise ValueError("resource position must be an integer")
        if self.position < 1:
            raise ValueError("resource position must start at 1")
        if self.media_type is not None:
            _require_text(self.media_type, "media_type")
        if self.filename is not None:
            _require_text(self.filename, "filename")
        if self.sha256 is not None:
            if len(self.sha256) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in self.sha256
            ):
                raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        if not isinstance(self.sensitive_locator, bool):
            raise ValueError("sensitive_locator must be a boolean")
        if self.public_locator is not None:
            _require_text(self.public_locator, "public_locator")
        object.__setattr__(self, "metadata", _metadata_dict(self.metadata))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "locator": (
                self.public_locator
                if self.sensitive_locator
                else self.public_locator or self.locator
            ),
            "sensitive_locator": self.sensitive_locator,
            "position": self.position,
            "media_type": self.media_type,
            "filename": self.filename,
            "sha256": self.sha256,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Part:
    id: str
    kind: PartKind
    title: str
    position: int
    source_url: str
    number: str | None = None
    resources: tuple[Resource, ...] = ()
    coverage: Coverage | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "part id")
        if not isinstance(self.kind, PartKind):
            raise ValueError("kind must be a PartKind")
        _require_text(self.title, "part title")
        if not isinstance(self.position, int) or isinstance(self.position, bool):
            raise ValueError("part position must be an integer")
        if self.position < 1:
            raise ValueError("part position must start at 1")
        _require_text(self.source_url, "part source_url")
        if self.number is not None:
            _require_text(self.number, "part number")
        if not isinstance(self.resources, tuple) or not all(
            isinstance(resource, Resource) for resource in self.resources
        ):
            raise ValueError("resources must be a tuple of Resource instances")
        if self.coverage is not None and not isinstance(self.coverage, Coverage):
            raise ValueError("coverage must be a Coverage or None")
        positions = [resource.position for resource in self.resources]
        if len(positions) != len(set(positions)):
            raise ValueError("resource positions must be unique within a part")
        object.__setattr__(self, "metadata", _metadata_dict(self.metadata))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "position": self.position,
            "number": self.number,
            "source_url": self.source_url,
            "coverage": self.coverage.to_manifest() if self.coverage else None,
            "resources": [resource.to_manifest() for resource in self.resources],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Publication:
    id: str
    work_id: str
    source_id: str
    title: str
    source_url: str
    parts: tuple[Part, ...] = ()
    coverage: Coverage | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "publication id")
        _require_text(self.work_id, "publication work_id")
        _require_text(self.source_id, "publication source_id")
        _require_text(self.title, "publication title")
        _require_text(self.source_url, "publication source_url")
        if not isinstance(self.parts, tuple) or not all(
            isinstance(part, Part) for part in self.parts
        ):
            raise ValueError("parts must be a tuple of Part instances")
        if self.coverage is not None and not isinstance(self.coverage, Coverage):
            raise ValueError("coverage must be a Coverage or None")
        positions = [part.position for part in self.parts]
        if len(positions) != len(set(positions)):
            raise ValueError("part positions must be unique within a publication")
        object.__setattr__(self, "metadata", _metadata_dict(self.metadata))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "work_id": self.work_id,
            "source_id": self.source_id,
            "title": self.title,
            "source_url": self.source_url,
            "coverage": self.coverage.to_manifest() if self.coverage else None,
            "parts": [part.to_manifest() for part in self.parts],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Work:
    id: str
    title: str
    publications: tuple[Publication, ...] = ()
    authors: tuple[str, ...] = ()
    artists: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    cover_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "work id")
        _require_text(self.title, "work title")
        if not isinstance(self.publications, tuple) or not all(
            isinstance(publication, Publication) for publication in self.publications
        ):
            raise ValueError("publications must be a tuple of Publication instances")
        for publication in self.publications:
            if publication.work_id != self.id:
                raise ValueError(
                    "every publication work_id must match the containing work id"
                )
        for field_name in ("authors", "artists", "genres"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise ValueError(f"{field_name} must be a tuple")
            for value in values:
                _require_text(value, field_name)
        if self.cover_url is not None:
            _require_text(self.cover_url, "cover_url")
        object.__setattr__(self, "metadata", _metadata_dict(self.metadata))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "authors": list(self.authors),
            "artists": list(self.artists),
            "genres": list(self.genres),
            "cover_url": self.cover_url,
            "publications": [
                publication.to_manifest() for publication in self.publications
            ],
            "metadata": dict(self.metadata),
        }
