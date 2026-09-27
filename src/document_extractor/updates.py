"""Source-neutral comparison of known and currently exposed publication parts."""

from __future__ import annotations

from .models import Confidence, Coverage, Part, Publication, UpdateResult
from .paths import canonical_source_identity


def part_identity(part: Part) -> tuple[str, str, str]:
    return (
        canonical_source_identity(part.source_url),
        str(part.number or "").casefold(),
        part.kind.value,
    )


def compare_part_updates(
    publication: Publication,
    known_parts: tuple[Part, ...],
    current_parts: tuple[Part, ...],
) -> UpdateResult:
    """Return only newly exposed parts while preserving current coverage evidence."""

    known = {part_identity(part) for part in known_parts}
    additions = tuple(
        part for part in current_parts if part_identity(part) not in known
    )
    coverage = publication.coverage or Coverage.from_counts(
        len(current_parts),
        None,
        unit="parts",
        evidence="current source inspection",
        confidence=Confidence.MEDIUM,
    )
    return UpdateResult(
        publication_id=publication.id,
        parts=additions,
        coverage=coverage,
    )
