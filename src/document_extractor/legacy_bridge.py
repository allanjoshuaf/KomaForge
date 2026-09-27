"""Normalize proven legacy manifests while the engine is migrated incrementally."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

from .models import (
    Confidence,
    Coverage,
    CoverageStatus,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
    Work,
)
from .paths import canonical_source_identity


class LegacyManifestError(ValueError):
    pass


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _part_kind(value: object) -> PartKind:
    normalized = str(value or "").casefold()
    if normalized == "chapter":
        return PartKind.CHAPTER
    if normalized == "volume":
        return PartKind.VOLUME
    if normalized in {"part", "book", "issue", "section"}:
        return PartKind.SECTION
    if normalized == "segment":
        return PartKind.SEGMENT
    return PartKind.DOCUMENT


def _resource_kind(page: dict) -> ResourceKind:
    raw_kind = str(page.get("resource_kind") or "").casefold()
    if raw_kind == "svg":
        return ResourceKind.SVG
    locator = str(page.get("url") or "")
    suffix = PurePosixPath(urlparse(locator).path).suffix.casefold()
    if suffix in {".svg", ".svgz"}:
        return ResourceKind.SVG
    return ResourceKind.IMAGE


def _has_sensitive_query(locator: str) -> bool:
    volatile = {"hash", "reqid", "session", "t", "token", "uid"}
    return bool(volatile.intersection(key.casefold() for key in parse_qs(urlparse(locator).query)))


def _resources_from_record(part_id: str, record: dict) -> tuple[Resource, ...]:
    resources: list[Resource] = []
    for position, page in enumerate(record.get("pages") or (), start=1):
        if not isinstance(page, dict):
            raise LegacyManifestError("page records must be dictionaries")
        locator = str(page.get("url") or "")
        if not locator:
            raise LegacyManifestError("page record has no source URL")
        page_number = int(page.get("page") or position)
        resources.append(
            Resource(
                id=_stable_id("resource", f"{part_id}:{page_number}:{locator}"),
                kind=_resource_kind(page),
                locator=locator,
                position=position,
                filename=str(page.get("file")) if page.get("file") else None,
                sha256=str(page.get("sha256")) if page.get("sha256") else None,
                sensitive_locator=_has_sensitive_query(locator),
                metadata={
                    key: value
                    for key, value in page.items()
                    if key not in {"url", "file", "sha256"}
                },
            )
        )
    return tuple(resources)


def _coverage_from_record(record: dict) -> Coverage:
    detected = int(record.get("detected") or record.get("page_count") or 0)
    expected_value = record.get("expected")
    expected = int(expected_value) if expected_value is not None else None
    coverage = Coverage.from_counts(
        detected,
        expected,
        unit=str(record.get("resource_unit") or "resources"),
        evidence=str(record.get("expected_source") or record.get("selector") or "legacy manifest"),
        confidence=Confidence.HIGH if expected is not None else Confidence.MEDIUM,
    )
    if record.get("status") == "complete" and expected is not None and not coverage.is_complete:
        raise LegacyManifestError(
            f"legacy record claims complete coverage with {detected}/{expected}"
        )
    return coverage


def normalize_legacy_manifest(manifest: dict, source_id: str) -> Work:
    """Build normalized models and reject contradictory legacy success claims."""

    if not isinstance(manifest, dict):
        raise LegacyManifestError("manifest must be a dictionary")
    source_url = str(manifest.get("source_url") or "")
    if not source_url:
        raise LegacyManifestError("manifest source_url is missing")
    publication_data = manifest.get("publication")
    if not isinstance(publication_data, dict):
        raise LegacyManifestError("manifest publication is missing")
    title = str(publication_data.get("title") or "").strip()
    if not title:
        raise LegacyManifestError("manifest publication title is missing")
    records = publication_data.get("chapters") or []
    if not isinstance(records, list):
        raise LegacyManifestError("manifest chapters must be a list")
    selected_count = int(publication_data.get("selected_part_count") or 0)
    if selected_count != len(records):
        raise LegacyManifestError(
            "selected_part_count does not match the normalized part records"
        )

    canonical = canonical_source_identity(source_url)
    work_id = _stable_id("work", canonical)
    parts: list[Part] = []
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise LegacyManifestError("chapter records must be dictionaries")
        part_url = str(record.get("source_url") or source_url)
        part_id = _stable_id(
            "part",
            f"{canonical_source_identity(part_url)}:{record.get('number', position)}",
        )
        coverage = _coverage_from_record(record)
        parts.append(
            Part(
                id=part_id,
                kind=_part_kind(record.get("kind")),
                title=str(record.get("title") or f"Part {position}"),
                position=int(record.get("index") or position),
                number=str(record.get("number")) if record.get("number") is not None else None,
                source_url=part_url,
                resources=_resources_from_record(part_id, record),
                coverage=coverage,
                metadata={"legacy_status": record.get("status")},
            )
        )

    availability = publication_data.get("availability")
    if isinstance(availability, dict):
        available = int(availability.get("accessible_part_count") or 0)
        expected = int(availability.get("catalog_part_count") or 0)
        publication_coverage = Coverage.from_counts(
            available,
            expected,
            unit="parts",
            evidence=str(availability.get("source") or "source catalog"),
            confidence=Confidence.HIGH,
            source_limited=bool(availability.get("access_limited")),
        )
    else:
        part_count = int(publication_data.get("part_count") or len(parts))
        publication_coverage = Coverage.from_counts(
            part_count,
            part_count,
            unit="parts",
            evidence="legacy publication structure",
            confidence=Confidence.MEDIUM,
        )

    publication_status = str(publication_data.get("status") or "")
    if (
        publication_status == "complete"
        and publication_coverage.status is CoverageStatus.SOURCE_LIMITED
    ):
        raise LegacyManifestError("source-limited publication claims complete status")
    if publication_status == "limited_by_source" and (
        publication_coverage.status is not CoverageStatus.SOURCE_LIMITED
    ):
        raise LegacyManifestError(
            "limited_by_source status has no matching coverage evidence"
        )

    publication = Publication(
        id=_stable_id("publication", canonical),
        work_id=work_id,
        source_id=source_id,
        title=title,
        source_url=source_url,
        parts=tuple(parts),
        coverage=publication_coverage,
        metadata={
            "legacy_type": publication_data.get("type"),
            "legacy_status": publication_status,
        },
    )
    return Work(id=work_id, title=title, publications=(publication,))
