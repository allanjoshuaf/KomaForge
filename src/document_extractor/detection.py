from __future__ import annotations

import base64
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse


from .detection_shared import (
    PAGE_TIMEOUT_MS, BLOB_CAPTURE_INIT_SCRIPT, INTERSTITIAL_PATTERN,
    ExpectedCount, ChapterLink, StructuredChapterCatalog, SelectablePart,
    CHAPTER_PATTERN, PART_PATTERN,
)

def normalize_manifest(raw_manifest: Any, base_url: str) -> list[dict]:
    if isinstance(raw_manifest, dict):
        raw_manifest = raw_manifest.get("pages", [])
    if not isinstance(raw_manifest, list):
        return []

    pages: list[dict] = []
    for position, item in enumerate(raw_manifest, start=1):
        if isinstance(item, str):
            raw_url, page_number = item, position
        elif isinstance(item, dict):
            raw_url = item.get("url") or item.get("src")
            page_number = item.get("page") or item.get("number") or position
        else:
            continue
        if not raw_url:
            continue
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = position
        pages.append(
            {
                "page": page_number,
                "url": urljoin(base_url, str(raw_url)),
                "source": "html-manifest",
            }
        )
    return pages


def pages_from_manifest(page) -> list[dict]:
    raw_manifest = page.evaluate(
        """
        () => {
            const node = document.querySelector(
                'script[type="application/json"][data-document-manifest]'
            );
            if (!node) return null;
            try { return JSON.parse(node.textContent); }
            catch (error) { return {__error: String(error)}; }
        }
        """
    )
    if isinstance(raw_manifest, dict) and raw_manifest.get("__error"):
        raise RuntimeError(
            "Le manifeste JSON intégré est invalide : " + raw_manifest["__error"]
        )
    return normalize_manifest(raw_manifest, page.url) if raw_manifest else []


def discover_pages(
    page, explicit_selector: str | None, expected: int | None
) -> tuple[list[dict], str]:
    from .reader_families import discover_resource_pages

    return discover_resource_pages(page, explicit_selector, expected)



from .part_detection import (
    looks_like_chapter_url,
    normalize_selector_input,
    normalize_chapter_candidates,
    discover_chapters,
    normalize_manga_up_catalog,
    discover_manga_up_catalog,
    _part_kind,
    normalize_selectable_part_candidates,
    discover_selectable_parts,
    select_chapters,
)


from .ebooks_navigation import (
    is_ebooks_product_url,
    _ebooks_reader_url,
    discover_linked_reader,
)


from .reader_controls import (
    dismiss_cookie_consent,
    access_interstitial_state,
    wait_for_access_interstitial,
    activate_reader_gate,
    wait_for_reader_readiness,
    inspect_render_surfaces,
    detect_expected_count,
    activate_reading_mode,
    hydrate_lazy_content,
)


from .image_candidates import (
    collect_image_candidates,
    collect_indexed_page_container_candidates,
    collect_chapter_reader_manifest,
    collect_virtual_blob_reader_candidates,
    collect_paginated_reader_candidates,
    _deduplicate,
    _auto_group,
)
