from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse


from .detection_shared import (
    ChapterLink,
    StructuredChapterCatalog,
    SelectablePart,
    CHAPTER_PATTERN,
    PART_PATTERN,
)

def looks_like_chapter_url(url: str) -> bool:
    parsed = urlparse(url)
    return CHAPTER_PATTERN.search(f"{parsed.path} {parsed.query}") is not None


def normalize_selector_input(value: str | None) -> str | None:
    """Accepte un sélecteur CSS ou une petite balise HTML copiée depuis F12."""
    if not value:
        return None
    value = value.strip()
    if not value.startswith("<"):
        return value

    tag_match = re.search(r"<\s*([a-zA-Z][\w-]*)", value)
    if not tag_match:
        raise ValueError("La balise HTML fournie dans --selector est invalide.")
    tag = tag_match.group(1).lower()

    id_match = re.search(r"\bid\s*=\s*(['\"])(.*?)\1", value, re.I)
    if id_match and re.fullmatch(r"[-_a-zA-Z][-_a-zA-Z0-9]*", id_match.group(2)):
        return f"{tag}#{id_match.group(2)}"

    class_match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", value, re.I)
    if class_match:
        classes = [
            item
            for item in class_match.group(2).split()
            if re.fullmatch(r"[-_a-zA-Z][-_a-zA-Z0-9]*", item)
        ]
        if classes:
            return tag + "".join(f".{item}" for item in classes)
    return tag


def normalize_chapter_candidates(
    candidates: list[dict],
    source_url: str,
    minimum: int = 3,
) -> list[ChapterLink]:
    """Conserve seulement un groupe fiable de liens de chapitres du même site."""
    source = urlparse(source_url)
    groups: dict[str, dict[str, tuple[Decimal, str, str, str]]] = defaultdict(dict)

    for candidate in candidates:
        raw_url = str(candidate.get("url") or "").strip()
        title = " ".join(str(candidate.get("title") or "").split())
        if not raw_url:
            continue
        absolute = urlparse(urljoin(source_url, raw_url))
        if (
            absolute.scheme not in {"http", "https"}
            or (absolute.hostname or "").lower() != (source.hostname or "").lower()
            or absolute.username
            or absolute.password
        ):
            continue

        clean_url = urlunparse(
            (absolute.scheme, absolute.netloc, absolute.path, absolute.params, absolute.query, "")
        )
        match = CHAPTER_PATTERN.search(title) or CHAPTER_PATTERN.search(absolute.path)
        if match is None:
            continue
        number = match.group(1).replace(",", ".")
        try:
            numeric = Decimal(number)
        except InvalidOperation:
            continue

        path_pattern = re.sub(r"[0-9]+(?:[._-][0-9]+)*", "#", absolute.path.lower())
        label = title or f"Chapitre {number}"
        groups[path_pattern][clean_url] = (numeric, number, label, clean_url)

    eligible = [list(group.values()) for group in groups.values() if len(group) >= minimum]
    if not eligible:
        return []
    eligible.sort(key=len, reverse=True)
    if len(eligible) > 1 and len(eligible[0]) == len(eligible[1]):
        return []

    by_number: dict[Decimal, tuple[Decimal, str, str, str]] = {}
    for item in eligible[0]:
        current = by_number.get(item[0])
        if current is None or len(item[3]) < len(current[3]):
            by_number[item[0]] = item
    ordered = sorted(by_number.values(), key=lambda item: (item[0], item[3]))
    if len(ordered) < minimum:
        return []
    return [
        ChapterLink(index=index, number=number, title=title, url=url)
        for index, (_numeric, number, title, url) in enumerate(ordered, start=1)
    ]


def discover_chapters(
    page,
    source_url: str,
    minimum: int = 3,
) -> list[ChapterLink]:
    candidates = page.locator("a[href]").evaluate_all(
        """
        links => links.slice(0, 5000).map(link => ({
            url: link.href,
            title: (link.innerText || link.getAttribute('aria-label') ||
                link.getAttribute('title') || '').trim()
        }))
        """
    )
    return normalize_chapter_candidates(candidates, source_url, minimum)


def normalize_manga_up_catalog(
    payload: dict,
    source_url: str,
) -> StructuredChapterCatalog | None:
    """Normalise le catalogue SSR sans confondre une partie avec l'oeuvre.

    Manga UP découpe souvent un chapitre papier en plusieurs lecteurs distincts.
    Les lecteurs gratuits sont signalés par ``consumptionType == 3`` dans les
    données Next.js rendues par le serveur. Les entrées payantes restent utiles
    pour annoncer honnêtement l'étendue du catalogue, mais elles ne sont jamais
    ajoutées à la file d'extraction d'une session publique.
    """
    parsed = urlparse(source_url)
    if (parsed.hostname or "").lower() != "global.manga-up.com":
        return None
    base_match = re.match(r"^(?P<base>(?:/[a-z]{2})?/manga/[0-9]+)/*$", parsed.path)
    if base_match is None:
        return None

    try:
        data = payload["props"]["pageProps"]["data"]
        raw_chapters = data["chapters"]
    except (KeyError, TypeError):
        return None
    if not isinstance(raw_chapters, list):
        return None

    catalog_entries: list[tuple[tuple[int, int], ChapterLink]] = []
    valid_total = 0
    base_url = urlunparse(
        (parsed.scheme, parsed.netloc, base_match.group("base"), "", "", "")
    )
    name_pattern = re.compile(
        r"^\s*(?:chapter|chapitre)\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*$",
        re.IGNORECASE,
    )
    for raw in raw_chapters:
        if not isinstance(raw, dict):
            continue
        name = " ".join(str(raw.get("mainName") or "").split())
        match = name_pattern.match(name)
        try:
            chapter_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        if not name or chapter_id <= 0:
            continue
        valid_total += 1
        if match is None:
            continue
        if raw.get("consumptionType") != 3 or raw.get("price") not in (None, 0):
            continue

        main_number = int(match.group(1))
        sub_number = int(match.group(2) or 0)
        number = str(main_number)
        if match.group(2) is not None:
            number += f" -{sub_number}"
        subtitle = " ".join(str(raw.get("subName") or "").split())
        title = name if not subtitle else f"{name} — {subtitle}"
        catalog_entries.append(
            (
                (main_number, sub_number),
                ChapterLink(
                    index=0,
                    number=number,
                    title=title,
                    url=f"{base_url}/{chapter_id}",
                ),
            )
        )

    if not catalog_entries:
        return None
    catalog_entries.sort(key=lambda item: item[0])
    chapters = tuple(
        ChapterLink(
            index=index,
            number=chapter.number,
            title=chapter.title,
            url=chapter.url,
        )
        for index, (_order, chapter) in enumerate(catalog_entries, start=1)
    )
    return StructuredChapterCatalog(
        chapters=chapters,
        total_count=valid_total,
        accessible_count=len(chapters),
        access_limited=valid_total > len(chapters),
        source="catalogue Next.js de Manga UP",
    )


def discover_manga_up_catalog(
    page,
    source_url: str,
) -> StructuredChapterCatalog | None:
    script = page.locator("script#__NEXT_DATA__")
    if script.count() == 0:
        return None
    try:
        payload = json.loads(script.first.text_content(timeout=5_000) or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return normalize_manga_up_catalog(payload, source_url)


def _part_kind(label: str) -> str:
    normalized = label.casefold().rstrip(".")
    if normalized in {"volume", "vol", "tome"}:
        return "volume"
    if normalized in {"chapter", "chapitre"}:
        return "chapter"
    if normalized in {"book", "livre"}:
        return "book"
    if normalized == "issue":
        return "issue"
    return "part"


def normalize_selectable_part_candidates(
    candidates: list[dict],
    minimum: int = 2,
) -> list[SelectablePart]:
    """Reconnaît un menu cohérent de volumes, tomes ou chapitres."""
    eligible: list[tuple[int, str, list[tuple[Decimal, str, str, str]]]] = []
    for candidate in candidates:
        selector = str(candidate.get("selector") or "").strip()
        if not selector:
            continue
        by_kind: dict[str, dict[Decimal, tuple[Decimal, str, str, str]]] = (
            defaultdict(dict)
        )
        for option in candidate.get("options") or []:
            title = " ".join(str(option.get("title") or "").split())
            value = str(option.get("value") or "")
            match = PART_PATTERN.search(title)
            if match is None:
                continue
            kind = _part_kind(match.group(1))
            number = match.group(2).replace(",", ".")
            try:
                numeric = Decimal(number)
            except InvalidOperation:
                continue
            by_kind[kind][numeric] = (numeric, number, title, value)

        groups = [
            (kind, sorted(values.values(), key=lambda item: item[0]))
            for kind, values in by_kind.items()
            if len(values) >= minimum
        ]
        if not groups:
            continue
        groups.sort(key=lambda item: len(item[1]), reverse=True)
        if len(groups) > 1 and len(groups[0][1]) == len(groups[1][1]):
            continue
        kind, parts = groups[0]
        eligible.append(
            (
                len(parts),
                selector,
                [(item[0], item[1], item[2], item[3]) for item in parts],
            )
        )

    if not eligible:
        return []
    eligible.sort(key=lambda item: item[0], reverse=True)
    if len(eligible) > 1 and eligible[0][0] == eligible[1][0]:
        return []

    _count, selector, parts = eligible[0]
    kind_match = PART_PATTERN.search(parts[0][2])
    kind = _part_kind(kind_match.group(1)) if kind_match else "part"
    return [
        SelectablePart(
            index=index,
            number=number,
            title=title,
            kind=kind,
            selector=selector,
            value=value,
        )
        for index, (_numeric, number, title, value) in enumerate(parts, start=1)
    ]


def discover_selectable_parts(
    page,
    minimum: int = 2,
    wait_timeout_ms: int = 0,
) -> list[SelectablePart]:
    def read_parts() -> list[SelectablePart]:
        candidates = page.locator("select").evaluate_all(
            r"""
            selects => selects.slice(0, 100).map(select => {
                const safeId = /^[-_a-zA-Z][-_a-zA-Z0-9]*$/.test(select.id || '')
                    ? `#${select.id}` : null;
                return {
                    selector: safeId,
                    options: [...select.options].map(option => ({
                        title: (option.textContent || '').trim(),
                        value: option.value
                    }))
                };
            })
            """
        )
        return normalize_selectable_part_candidates(candidates, minimum)

    parts = read_parts()
    if parts or wait_timeout_ms <= 0:
        return parts

    has_delayed_menu_hint = page.evaluate(
        r"""
        () => [...document.querySelectorAll('select')].some(select => {
            const label = select.labels?.length
                ? [...select.labels].map(node => node.textContent).join(' ') : '';
            const context = [select.id, select.name,
                select.getAttribute('aria-label'), label,
                [...select.options].map(option => option.textContent).join(' ')]
                .join(' ');
            return /(chapter|chapitre|volume|tome|book|livre|issue)/i.test(context);
        })
        """
    )
    if not has_delayed_menu_hint:
        return []

    deadline = time.monotonic() + wait_timeout_ms / 1000
    while time.monotonic() < deadline:
        time.sleep(0.25)
        parts = read_parts()
        if parts:
            return parts
    return []


def select_chapters(chapters: list[Any], expression: str) -> list[Any]:
    """Sélectionne des parties par leur position : all ou 1-3,5."""
    value = (expression or "all").strip().lower()
    if value in {"all", "tous", "tout", "*"}:
        return list(chapters)
    if not value:
        raise ValueError("La sélection de parties est vide.")

    selected: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            raise ValueError("Sélection de parties invalide.")
        if re.fullmatch(r"[0-9]+", token):
            selected.add(int(token))
            continue
        match = re.fullmatch(r"([0-9]+)\s*-\s*([0-9]+)", token)
        if match is None:
            raise ValueError(
                "Sélection de parties invalide. Utilisez all ou 1-3,5."
            )
        start, end = (int(match.group(1)), int(match.group(2)))
        if start > end:
            raise ValueError("Une plage de chapitres est inversée.")
        selected.update(range(start, end + 1))

    available = {int(chapter.index) for chapter in chapters}
    unknown = sorted(selected - available)
    if unknown:
        raise ValueError(
            "Partie(s) hors plage : " + ", ".join(str(item) for item in unknown)
        )
    result = [chapter for chapter in chapters if int(chapter.index) in selected]
    if not result:
        raise ValueError("Aucune partie sélectionnée.")
    return result
