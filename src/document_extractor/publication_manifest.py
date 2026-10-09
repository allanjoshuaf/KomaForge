"""Construction et mise à jour des manifestes de publication."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .chapter_tasks import merge_chapter_records


SINGLE_DOCUMENT_FIELDS = (
    "reading_mode",
    "selector",
    "expected",
    "expected_source",
    "detected",
    "resource_count",
    "resource_unit",
    "reader_expected",
    "source_visible_page_count",
    "recovered_from_detached_tree",
    "saved",
    "missing",
    "missing_count",
    "quality",
    "pdf_diagnostics",
    "epub_spine_items",
    "epub_diagnostics",
    "render_dpi",
    "source_sha256",
    "watermarks_removed",
    "pages",
    "artifact",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_publication_manifest(
    *,
    source_url: str,
    provider: str | None,
    requested_output_format: str,
    watermark_policy: str,
    watermark_texts: list[str],
    publication_type: str,
    output_title: str,
    source_title: str,
    source_metadata: dict,
    part_kind: str,
    part_count: int,
    selected_part_count: int,
    catalog_part_count: int | None = None,
    accessible_part_count: int | None = None,
    source_limited: bool = False,
    availability_source: str | None = None,
) -> dict:
    manifest = {
        "source_url": source_url,
        "provider": provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_format": requested_output_format,
        "watermark_policy": watermark_policy,
        "watermark_texts": list(watermark_texts),
        "publication": {
            "type": publication_type,
            "title": output_title,
            "source_title": source_title,
            "source_metadata": dict(source_metadata),
            "part_kind": part_kind,
            "part_count": part_count,
            "selected_part_count": selected_part_count,
            "chapter_count": part_count,
            "selected_chapter_count": selected_part_count,
            "chapters": [],
        },
    }
    if catalog_part_count is not None or accessible_part_count is not None:
        manifest["publication"]["availability"] = {
            "catalog_part_count": catalog_part_count,
            "accessible_part_count": accessible_part_count,
            "selected_accessible_part_count": selected_part_count,
            "access_limited": source_limited,
            "source": availability_source,
        }
    return manifest


def select_stored_chapter_records(
    existing: list[dict],
    current: list[dict],
    *,
    publication_is_work: bool,
    inspect: bool,
) -> list[dict]:
    if publication_is_work and not inspect:
        return merge_chapter_records(existing, current)
    return list(current)


def update_manifest_progress(
    manifest: dict,
    stored_chapters: list[dict],
    *,
    completed: bool,
    publication_is_work: bool,
    all_part_count: int,
    source_limited: bool,
) -> bool:
    publication = manifest["publication"]
    publication["chapters"] = stored_chapters
    publication["selected_part_count"] = len(stored_chapters)
    publication["selected_chapter_count"] = len(stored_chapters)
    if "availability" in publication:
        publication["availability"]["selected_accessible_part_count"] = len(
            stored_chapters
        )
    work_complete = completed and (
        not publication_is_work
        or (
            len(stored_chapters) >= all_part_count
            and all(item.get("status") == "complete" for item in stored_chapters)
        )
    )
    publication["status"] = (
        "limited_by_source"
        if work_complete and source_limited
        else "complete"
        if work_complete
        else "incomplete"
    )
    return work_complete


def flatten_single_document_manifest(manifest: dict, record: dict) -> None:
    manifest["publication"]["chapters"] = [
        {
            "index": record["index"],
            "number": record["number"],
            "title": record["title"],
            "kind": record["kind"],
            "source_url": record["source_url"],
            "page_count": record.get("detected", 0),
            "status": record.get("status"),
        }
    ]
    for key in SINGLE_DOCUMENT_FIELDS:
        if key in record:
            manifest[key] = record[key]
