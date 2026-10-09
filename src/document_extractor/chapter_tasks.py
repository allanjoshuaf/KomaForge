"""Planification et identité des parties d'une publication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .detection import ExpectedCount, select_chapters
from .models import Confidence, Part, Publication
from .paths import canonical_source_identity, safe_slug


@dataclass(frozen=True)
class ChapterTask:
    index: int
    number: str
    title: str
    source_url: str
    pages: list[dict] | None = None
    expected: ExpectedCount | None = None
    kind: str = "chapter"
    control_selector: str | None = None
    control_value: str | None = None
    adapter_part: Part | None = None


def chapter_record_identity(record: dict) -> tuple[str, str]:
    return (
        canonical_source_identity(str(record.get("source_url") or "")),
        str(record.get("number") or ""),
    )


def merge_chapter_records(
    existing: list[dict],
    current: list[dict],
) -> list[dict]:
    """Conserve les parties téléchargées et remplace les entrées actualisées."""

    merged: dict[tuple[str, str], dict] = {}
    for record in (*existing, *current):
        if not isinstance(record, dict):
            raise ValueError("chapter records must be dictionaries")
        identity = chapter_record_identity(record)
        if not identity[0]:
            raise ValueError("chapter record source URL cannot be empty")
        previous = merged.get(identity)
        if (
            previous is not None
            and record.get("status") == "error"
            and previous.get("status") == "complete"
        ):
            continue
        merged[identity] = record

    def order(record: dict) -> tuple[int, str, str]:
        try:
            position = int(record.get("index"))
        except (TypeError, ValueError):
            position = 2**31 - 1
        identity = chapter_record_identity(record)
        return position, identity[1], identity[0]

    return sorted(merged.values(), key=order)


def existing_chapter_records(manifest_path: Path, source_url: str) -> list[dict]:
    if not manifest_path.is_file():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if canonical_source_identity(str(payload.get("source_url") or "")) != (
        canonical_source_identity(source_url)
    ):
        raise RuntimeError("existing publication manifest belongs to another source")
    publication = payload.get("publication")
    records = publication.get("chapters") if isinstance(publication, dict) else None
    if not isinstance(records, list):
        raise RuntimeError("existing publication manifest has no chapter records")
    return [dict(record) for record in records]


def chapter_tasks_from_publication(publication: Publication) -> list[ChapterTask]:
    """Traduit la sortie normalisée d'un adaptateur en tâches de Core."""

    confidence_labels = {
        Confidence.LOW: "faible",
        Confidence.MEDIUM: "moyenne",
        Confidence.HIGH: "élevée",
    }
    tasks: list[ChapterTask] = []
    for part in sorted(publication.parts, key=lambda item: item.position):
        pages = [
            {
                "page": resource.position,
                "url": resource.locator,
                **dict(resource.metadata),
            }
            for resource in sorted(part.resources, key=lambda item: item.position)
        ]
        coverage = part.coverage
        expected = (
            ExpectedCount(
                coverage.expected,
                coverage.evidence or f"adaptateur {publication.source_id}",
                confidence_labels[coverage.confidence],
            )
            if coverage is not None and coverage.expected is not None
            else None
        )
        kind = part.kind.value
        if (
            kind == "document"
            and publication.metadata.get("publication_type") == "book"
        ):
            kind = "book"
        tasks.append(
            ChapterTask(
                index=part.position,
                number=part.number or str(part.position),
                title=part.title,
                source_url=part.source_url,
                pages=pages or None,
                expected=expected,
                kind=kind,
                adapter_part=part,
            )
        )
    return tasks


def expected_from_continuous_indices(pages: list[dict]) -> ExpectedCount | None:
    try:
        indices = sorted(int(item["document_index"]) for item in pages)
    except (KeyError, TypeError, ValueError):
        return None
    if indices in (
        list(range(0, len(pages))),
        list(range(1, len(pages) + 1)),
    ):
        return ExpectedCount(
            len(pages),
            "séquence data-index continue",
            "élevée",
        )
    return None


def chapter_stem(chapter: ChapterTask) -> str:
    label = safe_slug(chapter.title)
    if label == "document":
        label = f"chapitre-{safe_slug(chapter.number)}"
    return safe_slug(f"{chapter.index:03d}-{label}")


def part_label(kind: str, plural: bool = False, language: str = "fr") -> str:
    labels_by_language = {
        "fr": {"volume": ("Volume", "Volumes"), "book": ("Livre", "Livres"), "issue": ("Numéro", "Numéros"), "chapter": ("Chapitre", "Chapitres"), "document": ("Document", "Documents"), "part": ("Partie", "Parties")},
        "en": {"volume": ("Volume", "Volumes"), "book": ("Book", "Books"), "issue": ("Issue", "Issues"), "chapter": ("Chapter", "Chapters"), "document": ("Document", "Documents"), "part": ("Part", "Parts")},
        "ru": {"volume": ("Том", "Тома"), "book": ("Книга", "Книги"), "issue": ("Выпуск", "Выпуски"), "chapter": ("Глава", "Главы"), "document": ("Документ", "Документы"), "part": ("Часть", "Части")},
        "zh": {"volume": ("卷", "卷"), "book": ("书籍", "书籍"), "issue": ("期", "期"), "chapter": ("章节", "章节"), "document": ("文档", "文档"), "part": ("部分", "部分")},
    }
    labels = labels_by_language.get(language, labels_by_language["fr"])
    singular, plural_label = labels.get(kind, labels["part"])
    return plural_label if plural else singular


def localized_runtime_value(value: str, language: str) -> str:
    translations = {
        "motif d'URL répété": {
            "en": "repeated URL pattern",
            "ru": "повторяющийся шаблон URL",
            "zh": "重复 URL 模式",
        },
        "séquence data-index continue": {
            "en": "continuous data-index sequence",
            "ru": "непрерывная последовательность data-index",
            "zh": "连续 data-index 序列",
        },
        "manifeste public Calaméo": {
            "en": "public Calaméo manifest",
            "ru": "публичный манифест Calaméo",
            "zh": "Calaméo 公共清单",
        },
        "aucun contrôle requis": {
            "en": "no control required",
            "ru": "дополнительное управление не требуется",
            "zh": "无需额外控制",
        },
        "ressources internes du navigateur": {
            "en": "internal browser resources",
            "ru": "внутренние ресурсы браузера",
            "zh": "浏览器内部资源",
        },
    }
    return translations.get(value, {}).get(language, value)


def resolve_part_selection(
    chapters: list[ChapterTask],
    expression: str,
    kind: str,
    default_expression: str = "1",
    language: str = "fr",
) -> list[ChapterTask]:
    if expression == "ask":
        noun = part_label(kind, plural=True, language=language).lower()
        prompts = {
            "fr": "Sélection des {noun} [1, all ou 1-3,5; défaut {default}] : ",
            "en": "Select {noun} [1, all, or 1-3,5; default {default}]: ",
            "ru": "Выберите {noun} [1, all или 1-3,5; по умолчанию {default}]: ",
            "zh": "选择{noun} [1、all 或 1-3,5；默认 {default}]：",
        }
        expression = (
            input(
                prompts.get(language, prompts["fr"]).format(
                    noun=noun,
                    default=default_expression,
                )
            ).strip()
            or default_expression
        )
    return select_chapters(chapters, expression)
