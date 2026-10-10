"""Normalize proven legacy manifests while the engine is migrated incrementally."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

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


_INTERSTITIAL_TITLES = {
    "attention required",
    "checking your browser",
    "just a moment",
}


def _recover_legacy_title(title: str, source_url: str) -> str:
    if title.casefold().strip(" .!-") not in _INTERSTITIAL_TITLES:
        return title
    slug = PurePosixPath(unquote(urlparse(source_url).path).rstrip("/")).name
    recovered = " ".join(part for part in re.split(r"[-_.]+", slug) if part)
    return recovered.title() if recovered else title


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
    keys = {
        key.casefold().strip("_-")
        for key in parse_qs(urlparse(locator).query)
    }
    return bool(volatile.intersection(keys))


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


def _upgrade_flat_manifest(manifest: dict, title_hint: str | None) -> dict:
    """Present pre-publication manifests through the current legacy shape."""

    if isinstance(manifest.get("publication"), dict):
        return manifest
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return manifest
    title = str(title_hint or "").strip()
    if not title:
        raise LegacyManifestError(
            "flat legacy manifest needs a title hint from its directory"
        )
    detected = int(manifest.get("detected") or len(pages))
    expected_value = manifest.get("expected")
    expected = int(expected_value) if expected_value is not None else None
    complete = (
        expected is not None
        and detected == expected
        and not (manifest.get("missing") or [])
    )
    status = "complete" if complete else "incomplete"
    record = {
        "index": 1,
        "number": "1",
        "title": title,
        "kind": "document",
        "source_url": manifest.get("source_url"),
        "status": status,
        "detected": detected,
        "expected": expected,
        "expected_source": manifest.get("expected_source"),
        "resource_unit": "resources",
        "pages": pages,
    }
    if isinstance(manifest.get("artifact"), dict):
        record["artifact"] = manifest["artifact"]
    upgraded = dict(manifest)
    upgraded["publication"] = {
        "type": "document",
        "title": title,
        "part_count": 1,
        "selected_part_count": 1,
        "chapters": [record],
        "status": status,
    }
    return upgraded


def normalize_legacy_manifest(
    manifest: dict,
    source_id: str,
    *,
    title_hint: str | None = None,
) -> Work:
    """Build normalized models and reject contradictory legacy success claims."""

    if not isinstance(manifest, dict):
        raise LegacyManifestError("manifest must be a dictionary")
    manifest = _upgrade_flat_manifest(manifest, title_hint)
    source_url = str(manifest.get("source_url") or "")
    if not source_url:
        raise LegacyManifestError("manifest source_url is missing")
    publication_data = manifest.get("publication")
    if not isinstance(publication_data, dict):
        raise LegacyManifestError("manifest publication is missing")
    title = str(publication_data.get("title") or "").strip()
    if not title:
        raise LegacyManifestError("manifest publication title is missing")
    title = _recover_legacy_title(title, source_url)
    records = publication_data.get("chapters") or []
    if not isinstance(records, list):
        raise LegacyManifestError("manifest chapters must be a list")
    if len(records) == 1 and isinstance(records[0], dict):
        record = dict(records[0])
        for key in (
            "detected",
            "expected",
            "expected_source",
            "resource_count",
            "resource_unit",
            "pages",
            "artifact",
        ):
            if key not in record and key in manifest:
                record[key] = manifest[key]
        records = [record]
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

    publication_status = str(publication_data.get("status") or "")
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
        part_coverages = [part.coverage for part in parts if part.coverage is not None]
        part_count = int(publication_data.get("part_count") or len(parts))
        known_totals = bool(part_coverages) and all(
            coverage.expected is not None for coverage in part_coverages
        )
        same_unit = len({coverage.unit for coverage in part_coverages}) == 1
        if publication_status == "incomplete" and selected_count < part_count:
            publication_coverage = Coverage.from_counts(
                selected_count,
                part_count,
                unit="parts",
                evidence="selected legacy publication parts",
                confidence=Confidence.HIGH,
            )
        elif publication_status != "complete" and known_totals and same_unit:
            publication_coverage = Coverage.from_counts(
                sum(coverage.available for coverage in part_coverages),
                sum(coverage.expected or 0 for coverage in part_coverages),
                unit=part_coverages[0].unit,
                evidence="aggregated legacy part coverage",
                confidence=Confidence.HIGH,
            )
        elif publication_status != "complete":
            publication_coverage = Coverage.from_counts(
                sum(coverage.available for coverage in part_coverages),
                None,
                unit=(part_coverages[0].unit if same_unit and part_coverages else "parts"),
                evidence="incomplete legacy publication",
                confidence=Confidence.MEDIUM,
            )
        else:
            publication_coverage = Coverage.from_counts(
                part_count,
                part_count,
                unit="parts",
                evidence="legacy publication structure",
                confidence=Confidence.MEDIUM,
            )

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

    source_metadata = publication_data.get("source_metadata")
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    publication = Publication(
        id=_stable_id("publication", canonical),
        work_id=work_id,
        source_id=source_id,
        title=title,
        source_url=source_url,
        parts=tuple(parts),
        coverage=publication_coverage,
        metadata={
            **source_metadata,
            "legacy_type": publication_data.get("type"),
            "legacy_status": publication_status,
        },
    )
    return Work(id=work_id, title=title, publications=(publication,))
