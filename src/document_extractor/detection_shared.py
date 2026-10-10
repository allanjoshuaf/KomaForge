from __future__ import annotations

import re
from dataclasses import dataclass


PAGE_TIMEOUT_MS = 90_000

BLOB_CAPTURE_INIT_SCRIPT = r"""
(() => {
    if (window.__komaforgeBlobStore) return;
    const create = URL.createObjectURL.bind(URL);
    const revoke = URL.revokeObjectURL.bind(URL);
    const blobs = new Map();
    const pages = new Map();
    let retainedBytes = 0;
    Object.defineProperty(window, '__komaforgeBlobStore', {value: blobs});
    Object.defineProperty(window, '__komaforgePageBlobStore', {value: pages});
    URL.createObjectURL = value => {
        const url = create(value);
        if (value instanceof Blob && value.size > 0 &&
            value.size <= 64 * 1024 * 1024 && blobs.size < 2000 &&
            retainedBytes + value.size <= 256 * 1024 * 1024) {
            blobs.set(url, value);
            retainedBytes += value.size;
        }
        return url;
    };
    URL.revokeObjectURL = url => revoke(url);
})();
"""

INTERSTITIAL_PATTERN = re.compile(
    r"(?:just a moment|checking your browser|verify you are human|"
    r"performing security verification|attention required[^\n]*cloudflare|"
    r"un instant|v[ée]rifions que vous [êe]tes humain)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExpectedCount:
    value: int
    source: str
    confidence: str


@dataclass(frozen=True)
class ChapterLink:
    index: int
    number: str
    title: str
    url: str


@dataclass(frozen=True)
class StructuredChapterCatalog:
    chapters: tuple[ChapterLink, ...]
    total_count: int
    accessible_count: int
    access_limited: bool
    source: str


@dataclass(frozen=True)
class SelectablePart:
    index: int
    number: str
    title: str
    kind: str
    selector: str
    value: str


CHAPTER_PATTERN = re.compile(
    r"(?i)(?:chapter|chapitre|cap[ií]tulo|episode|épisode|ch\.?)"
    r"(?:\s|[-_/#.:])*([0-9]+(?:[.,][0-9]+)?)"
)

PART_PATTERN = re.compile(
    r"(?i)\b(volume|vol\.?|tome|chapter|chapitre|issue|book|livre)"
    r"(?:\s|[-_/#.:])*([0-9]+(?:[.,][0-9]+)?)\b"
)
