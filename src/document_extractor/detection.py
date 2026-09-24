from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse


PAGE_TIMEOUT_MS = 90_000


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


def activate_reader_gate(page) -> dict | None:
    """Active un bouton explicite qui met en route un aperçu déjà ouvert."""
    candidate = page.evaluate(
        r"""
        () => {
            const normal = value => String(value || '').normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '').toLowerCase()
                .replace(/\s+/g, ' ').trim();
            const roots = [document];
            const seen = new Set(roots);
            for (let index = 0; index < roots.length; index++) {
                for (const node of roots[index].querySelectorAll('*')) {
                    if (node.shadowRoot && !seen.has(node.shadowRoot)) {
                        seen.add(node.shadowRoot);
                        roots.push(node.shadowRoot);
                    }
                    if (node.tagName === 'IFRAME') {
                        try {
                            if (node.contentDocument && !seen.has(node.contentDocument)) {
                                seen.add(node.contentDocument);
                                roots.push(node.contentDocument);
                            }
                        } catch (_) {
                            // Les contrôles d'une iframe externe ne sont pas manipulés.
                        }
                    }
                }
            }
            const controls = roots.flatMap(root => [...root.querySelectorAll(
                'button, [role="button"], input[type="button"], input[type="submit"], a'
            )]);
            const exact = /^(?:(?:load|resume|continue|open|start)(?: this)? (?:preview|book preview|document preview|reader|reading|book|document)|(?:charger|reprendre|continuer|ouvrir|commencer)(?: cet?| le| la)? (?:apercu|livre|document|lecteur|lecture))$/;
            const forbidden = /(sign.?in|log.?in|register|subscribe|purchase|buy|pay|download|connexion|inscription|abonn|acheter|payer|telecharger)/;
            for (const control of controls) {
                const style = getComputedStyle(control);
                const rect = control.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' ||
                    rect.width <= 0 || rect.height <= 0 || control.disabled ||
                    control.hasAttribute('data-komaforge-reader-gate')) continue;
                const label = normal(
                    control.getAttribute('aria-label') || control.textContent ||
                    control.value || control.getAttribute('title')
                );
                if (!exact.test(label) || forbidden.test(label)) continue;
                const marker = `gate-${Date.now()}-${Math.random().toString(36).slice(2)}`;
                control.setAttribute('data-komaforge-reader-gate', marker);
                return {marker, label};
            }
            return null;
        }
        """
    )
    if not candidate:
        return None

    control = page.locator(
        f'[data-komaforge-reader-gate="{candidate["marker"]}"]'
    ).first
    try:
        control.click(timeout=10_000)
    except Exception:
        control.evaluate("node => node.click()")
    time.sleep(0.5)
    return {
        "action": f"clic -> {candidate['label']}",
        "source": "démarrage automatique du lecteur",
    }


def wait_for_reader_readiness(page, timeout_ms: int = 20_000) -> dict:
    """Attend un lecteur encore explicitement en cours d'initialisation."""

    def state() -> dict:
        return page.evaluate(
            r"""
            () => {
                const deepRoots = () => {
                    const roots = [document];
                    const seen = new Set(roots);
                    for (let index = 0; index < roots.length; index++) {
                        const root = roots[index];
                        for (const node of root.querySelectorAll('*')) {
                            if (node.shadowRoot && !seen.has(node.shadowRoot)) {
                                seen.add(node.shadowRoot);
                                roots.push(node.shadowRoot);
                            }
                            if (node.tagName === 'IFRAME') {
                                try {
                                    if (node.contentDocument && !seen.has(node.contentDocument)) {
                                        seen.add(node.contentDocument);
                                        roots.push(node.contentDocument);
                                    }
                                } catch (_) {
                                    // Une iframe externe reste détectable comme surface.
                                }
                            }
                        }
                    }
                    return roots;
                };
                const roots = deepRoots();
                const all = selector => roots.flatMap(
                    root => [...root.querySelectorAll(selector)]
                );
                const body = (document.body?.innerText || '')
                    .replace(/\s+/g, ' ').slice(0, 5000);
                const aria = all('[aria-label]')
                    .map(node => node.getAttribute('aria-label') || '').join(' ');
                const visibleCanvas = all('canvas').some(canvas => {
                    const rect = canvas.getBoundingClientRect();
                    return rect.width >= 200 && rect.height >= 200;
                });
                const pageSignal = /page\s+\S+\s*\(page\s*\d+\s*(?:of|sur|\/)\s*\d+\)/i
                    .test(aria) || /page\s*\d+\s*(?:of|sur|\/)\s*\d+/i
                    .test(`${aria} ${body}`);
                const likelyImages = all('img').filter(image => {
                    const text = `${image.id} ${image.className} ${image.alt}`;
                    return /(page|scan|chapter|chapitre|volume|manga|comic)/i.test(text) &&
                        !/(logo|icon|avatar|advert|sponsor|thumbnail|hero)/i.test(text);
                }).length;
                const readerHint = all(
                    '#readingsystem-viewport, [aria-label*="book content" i], ' +
                    '[id*="reader" i], [class*="reader" i], ' +
                    '[id*="pdf" i], [class*="pdf" i]'
                ).length > 0 || /(?:reader|lecteur)/i.test(document.title);
                const loading = /(loading\.{0,3}|preparing your (?:book|document))/i
                    .test(`${document.title} ${body}`);
                return {loading, ready: pageSignal || visibleCanvas || likelyImages >= 2,
                    pageSignal, visibleCanvas, likelyImages, readerHint};
            }
            """
        )

    first = state()
    if first["ready"] or (not first["loading"] and not first["readerHint"]):
        return {**first, "waited_ms": 0}
    deadline = time.monotonic() + timeout_ms / 1000
    waited_ms = 0
    current = first
    while time.monotonic() < deadline:
        time.sleep(0.25)
        waited_ms += 250
        current = state()
        if current["ready"] or (
            not current["loading"] and not current["readerHint"]
        ):
            break
    return {**current, "waited_ms": waited_ms}


def inspect_render_surfaces(page) -> dict:
    """Inventorie les lecteurs canvas/iframe sans prétendre extraire leurs pixels."""
    return page.evaluate(
            r"""
        () => {
            const deepRoots = () => {
                const roots = [document];
                const seen = new Set(roots);
                for (let index = 0; index < roots.length; index++) {
                    const root = roots[index];
                    for (const node of root.querySelectorAll('*')) {
                        if (node.shadowRoot && !seen.has(node.shadowRoot)) {
                            seen.add(node.shadowRoot);
                            roots.push(node.shadowRoot);
                        }
                        if (node.tagName === 'IFRAME') {
                            try {
                                if (node.contentDocument && !seen.has(node.contentDocument)) {
                                    seen.add(node.contentDocument);
                                    roots.push(node.contentDocument);
                                }
                            } catch (_) {
                                // Une iframe externe reste détectable comme surface.
                            }
                        }
                    }
                }
                return roots;
            };
            const roots = deepRoots();
            const all = selector => roots.flatMap(
                root => [...root.querySelectorAll(selector)]
            );
            const visible = node => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width >= 100 && rect.height >= 100 &&
                    style.display !== 'none' && style.visibility !== 'hidden';
            };
            const canvases = all('canvas')
                .filter(visible).map(canvas => ({
                    width: canvas.width,
                    height: canvas.height,
                    className: String(canvas.className || ''),
                    parentClass: String(canvas.parentElement?.className || '')
                }));
            const frames = all('iframe')
                .filter(frame => visible(frame) ||
                    /(page|reader|text.?layer|document)/i.test(
                        `${frame.title} ${frame.className}`
                    ))
                .map(frame => ({title: frame.title,
                    className: String(frame.className || '')}));
            const texts = all(
                '[aria-label], input[placeholder], [role="slider"]'
            ).map(node => `${node.getAttribute('aria-label') || ''} ` +
                `${node.getAttribute('placeholder') || ''}`);
            const pageCounts = [];
            for (const text of texts) {
                const match = text.match(/page\s*\d+\s*(?:of|sur|\/)\s*(\d+)/i);
                if (match) pageCounts.push(Number(match[1]));
            }
            for (const slider of all(
                'input[type="range"][aria-label*="page" i], [role="slider"][aria-label*="page" i]'
            )) {
                const maximum = Number(slider.max || slider.getAttribute('aria-valuemax'));
                if (Number.isFinite(maximum) && maximum >= 0) pageCounts.push(maximum + 1);
            }
            const readerHints = all(
                '#readingsystem-viewport, [aria-label*="book content" i], ' +
                '[id*="reader" i], [class*="reader" i], ' +
                '[id*="pdf" i], [class*="pdf" i]'
            );
            return {
                canvas_count: canvases.length,
                iframe_count: frames.length,
                canvases,
                frames,
                reader_hint: readerHints.length > 0,
                accessible_page_count: pageCounts.length ? Math.max(...pageCounts) : null
            };
        }
        """
    )


def detect_expected_count(page) -> ExpectedCount | None:
    candidates = page.evaluate(
        r"""
        () => {
            const found = [];
            const add = (value, source, score) => {
                const number = Number.parseInt(String(value), 10);
                if (Number.isFinite(number) && number > 0 && number <= 100000) {
                    found.push({value: number, source, score});
                }
            };

            const meta = document.querySelector('meta[name="document-page-count"]');
            if (meta) add(meta.content, 'meta document-page-count', 100);

            const manifest = document.querySelector(
                'script[type="application/json"][data-document-manifest]'
            );
            if (manifest) {
                try {
                    const parsed = JSON.parse(manifest.textContent);
                    const pages = Array.isArray(parsed) ? parsed : parsed.pages;
                    if (Array.isArray(pages)) add(pages.length, 'manifeste HTML', 100);
                } catch (_) {}
            }

            for (const node of document.querySelectorAll(
                '[data-page-count], [data-total-pages], [data-pages-total]'
            )) {
                add(
                    node.dataset.pageCount || node.dataset.totalPages ||
                    node.dataset.pagesTotal,
                    'attribut de compteur',
                    95
                );
            }

            const selectors = [
                '[class*="page" i]', '[id*="page" i]',
                '[class*="reader" i]', '[id*="reader" i]',
                '[aria-label*="page" i]'
            ];
            const nodes = [...new Set(selectors.flatMap(
                selector => [...document.querySelectorAll(selector)]
            ))].slice(0, 1000);
            const patterns = [
                /\bpage\s*\d+\s*(?:\/|sur|of)\s*(\d+)\b/i,
                /\b\d+\s*(?:\/|sur|of)\s*(\d+)\s*pages?\b/i,
                /\b(\d+)\s*pages?\b/i,
                /(?:^|\s)\d+\s*\/\s*(\d+)(?:\s|$)/
            ];
            for (const node of nodes) {
                const text = `${node.textContent || ''} ${node.getAttribute('aria-label') || ''}`
                    .replace(/\s+/g, ' ').trim();
                if (text.length > 300) continue;
                for (const pattern of patterns) {
                    const match = text.match(pattern);
                    if (match) add(match[1], `compteur visible: ${text.slice(0, 80)}`, 85);
                }
            }

            const bodyText = (document.body?.innerText || '').replace(/\s+/g, ' ');
            for (const pattern of patterns.slice(0, 2)) {
                const match = bodyText.match(pattern);
                if (match) add(match[1], 'texte de la page', 65);
            }
            return found;
        }
        """
    )
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (item["score"], item["value"]))
    confidence = "élevée" if best["score"] >= 90 else "moyenne"
    return ExpectedCount(int(best["value"]), str(best["source"]), confidence)


def activate_reading_mode(
    page,
    explicit_selector: str | None,
    explicit_value: str | None,
    auto_enabled: bool,
) -> dict | None:
    if explicit_selector:
        control = page.locator(explicit_selector).first
        control.wait_for(state="visible", timeout=PAGE_TIMEOUT_MS)
        tag_name = control.evaluate("node => node.tagName.toLowerCase()")
        if explicit_value is not None:
            if tag_name != "select":
                raise RuntimeError(
                    "--reading-mode-value exige que le contrôle soit un <select>."
                )
            control.select_option(explicit_value)
            action = f"{explicit_selector} = {explicit_value}"
        else:
            control.click()
            action = f"clic sur {explicit_selector}"
        time.sleep(0.8)
        return {"action": action, "source": "option explicite"}

    if not auto_enabled:
        return None

    # Compatibilité directe avec la configuration qui fonctionnait déjà :
    # --reading-mode-selector "#readingmode" --reading-mode-value "full".
    # Cette paire est essayée avant toute heuristique.
    exact = page.locator("#readingmode").first
    challenge = page.evaluate(
        r"""
        () => /(just a moment|cloudflare|checking your browser|verification|vérification)/i
            .test(`${document.title} ${(document.body?.innerText || '').slice(0, 2000)}`)
        """
    )
    if exact.count() or challenge:
        try:
            exact.wait_for(state="visible", timeout=60_000 if challenge else 10_000)
        except Exception:
            pass
    if exact.count():
        options = exact.locator("option")
        values = [options.nth(index).get_attribute("value") for index in range(options.count())]
        if "full" in values:
            previous_images = page.locator("img").count()
            exact.select_option("full")
            try:
                page.wait_for_function(
                    "previous => document.querySelectorAll('img').length > previous",
                    arg=previous_images,
                    timeout=60_000,
                )
            except Exception:
                time.sleep(0.75)
            return {
                "action": "#readingmode = full",
                "source": "valeur automatique prioritaire",
            }

    candidate = page.evaluate(
        r"""
        () => {
            const normal = value => String(value || '').normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
            const visible = node => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0 && !node.disabled;
            };
            const strong = /^(full|all|all pages|continuous|continu|vertical|scroll|long strip|webtoon|toutes les pages|tout afficher|lecture verticale|defilement)$/;
            const useful = /(full|all pages|continuous|continu|vertical|scroll|long strip|webtoon|toutes les pages|tout afficher|lecture verticale|defilement)/;
            const contextWords = /(reading.?mode|reader.?mode|readermode|lecture|reader|display|affichage|mode)/;
            const results = [];

            [...document.querySelectorAll('select')].forEach((select, index) => {
                if (!visible(select)) return;
                const label = select.labels?.length
                    ? [...select.labels].map(node => node.textContent).join(' ') : '';
                const context = normal([
                    select.id, select.name, select.className,
                    select.getAttribute('aria-label'), label
                ].join(' '));
                [...select.options].forEach(option => {
                    const value = normal(option.value);
                    const text = normal(option.textContent);
                    let score = 0;
                    if (select.id.toLowerCase() === 'readingmode') score += 14;
                    if (contextWords.test(context)) score += 6;
                    if (value === 'full') score += 14;
                    if (strong.test(value) || strong.test(text)) score += 12;
                    else if (useful.test(`${value} ${text}`)) score += 8;
                    if (option.disabled) score = -1;
                    results.push({kind: 'select', index, value: option.value,
                        label: option.textContent.trim(), score,
                        alreadyActive: option.selected});
                });
            });

            const buttons = [...document.querySelectorAll(
                'button, [role="button"], input[type="button"], input[type="radio"]'
            )];
            buttons.forEach((button, index) => {
                if (!visible(button)) return;
                const searchable = normal([
                    button.textContent, button.value, button.id, button.name,
                    button.className, button.getAttribute('aria-label'),
                    button.getAttribute('title')
                ].join(' '));
                const displayLabel = [button.textContent,
                    button.getAttribute('aria-label'), button.getAttribute('title'),
                    button.value, button.id].map(normal).find(Boolean) || '';
                let score = 0;
                if (useful.test(displayLabel)) score += 12;
                if (useful.test(displayLabel) && contextWords.test(searchable)) score += 5;
                if (/show.?all/.test(displayLabel)) score += 6;
                results.push({kind: 'button', index,
                    label: displayLabel.slice(0, 100), score});
            });
            results.sort((a, b) => b.score - a.score);
            return results[0] || null;
        }
        """
    )
    if not candidate:
        return None
    if candidate["kind"] == "button":
        label = candidate.get("label", "")
        if re.search(
            r"\b(fullscreen|full screen|plein ecran|scroll to (?:top|bottom)|"
            r"back to top|next|previous|precedent|suivant)\b",
            label,
        ):
            return None
    threshold = 10 if candidate["kind"] == "select" else 12
    if candidate["score"] < threshold:
        return None

    if candidate["kind"] == "select":
        control = page.locator("select").nth(candidate["index"])
        if not candidate.get("alreadyActive"):
            control.select_option(candidate["value"])
            time.sleep(0.8)
        return {
            "action": f"select -> {candidate['label']} ({candidate['value']})",
            "source": "détection automatique",
            "score": candidate["score"],
        }

    controls = page.locator(
        'button, [role="button"], input[type="button"], input[type="radio"]'
    )
    controls.nth(candidate["index"]).click()
    time.sleep(0.8)
    return {
        "action": f"clic -> {candidate['label']}",
        "source": "détection automatique",
        "score": candidate["score"],
    }


def hydrate_lazy_content(
    page,
    expected: int | None,
    max_steps: int = 400,
    minimum_steps: int = 20,
) -> dict:
    """Fait défiler le lecteur pour matérialiser les pages chargées à la demande."""
    stable_bottom = 0
    stable_expected = 0
    stable_progress = 0
    previous = None
    steps = 0
    for steps in range(1, max_steps + 1):
        state = page.evaluate(
            """
            () => {
                const images = [...document.images];
                const urls = images.map(img => img.dataset.src ||
                    img.dataset.lazySrc || img.dataset.original || img.dataset.url ||
                    img.getAttribute('data-lazy') || img.currentSrc || img.src || '');
                const unresolved = urls.map((url, index) => ({url, index}))
                    .filter(item => !item.url ||
                        /(loading|placeholder|spinner|transparent|blank)(?:img)?\.(?:gif|png|webp|svg)(?:[?#]|$)/i
                            .test(item.url));
                return {
                    imageCount: urls.filter(Boolean).length,
                    resolvedCount: urls.length - unresolved.length,
                    uniqueCount: new Set(urls.filter(Boolean)).size,
                    unresolved: unresolved.map(item => item.index),
                    height: Math.max(document.body?.scrollHeight || 0,
                        document.documentElement?.scrollHeight || 0),
                    y: window.scrollY,
                    viewport: window.innerHeight
                };
            }
            """
        )
        at_bottom = state["y"] + state["viewport"] >= state["height"] - 4
        signature = (state["resolvedCount"], state["uniqueCount"], state["height"])
        if expected and state["resolvedCount"] >= expected:
            stable_expected += 1
        else:
            stable_expected = 0
        if stable_expected >= 3:
            break
        if at_bottom and signature == previous:
            stable_bottom += 1
        else:
            stable_bottom = 0
        if signature == previous:
            stable_progress += 1
        else:
            stable_progress = 0
        if stable_bottom >= 3 and steps >= minimum_steps:
            break
        if stable_progress >= minimum_steps and steps >= minimum_steps:
            break
        previous = signature
        if state["unresolved"]:
            target = state["unresolved"][(steps - 1) % len(state["unresolved"])]
            page.locator("img").nth(target).scroll_into_view_if_needed(timeout=5_000)
        else:
            page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 4, 2400))")
        time.sleep(0.10)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.25)
    return {
        "steps": steps,
        "images_seen": state["imageCount"],
        "images_ready": state["resolvedCount"],
    }


def collect_image_candidates(page, selector: str) -> list[dict]:
    locator = page.locator(selector)
    if not locator.count():
        raise RuntimeError(f"Aucune image ne correspond au sélecteur : {selector}")
    locator.first.wait_for(state="attached", timeout=PAGE_TIMEOUT_MS)
    return locator.evaluate_all(
        r"""
        (images) => images.map((image, position) => {
            const srcset = image.getAttribute('srcset') || image.dataset.srcset || '';
            const srcsetLast = srcset.split(',').map(item => item.trim().split(/\s+/)[0])
                .filter(Boolean).at(-1);
            const raw = image.dataset.src || image.dataset.lazySrc ||
                image.dataset.original || image.dataset.url ||
                image.getAttribute('data-lazy') || srcsetLast ||
                image.currentSrc || image.src || null;
            let url = null;
            try { url = raw ? new URL(raw, document.baseURI).href : null; }
            catch (_) {}

            const rect = image.getBoundingClientRect();
            const width = Number(image.getAttribute('width')) ||
                image.naturalWidth || rect.width || 0;
            const height = Number(image.getAttribute('height')) ||
                image.naturalHeight || rect.height || 0;
            const text = [image.id, image.className, image.alt, image.src,
                image.parentElement?.id, image.parentElement?.className]
                .join(' ').toLowerCase();
            const decorative = /(logo|icon|avatar|emoji|banner|advert|sponsor|thumbnail|hero|favicon)/
                .test([image.id, image.className, image.alt,
                    image.getAttribute('role')].join(' ').toLowerCase());
            let score = 0;
            if (/(page|scan|reader|document|chapter|manga|comic)/.test(text)) score += 6;
            if (/(logo|icon|avatar|emoji|banner|advert|sponsor|thumbnail)/.test(text)) score -= 10;
            if (width >= 500) score += 2;
            if (height >= 700) score += 3;
            if (height > width * 1.1) score += 2;
            if (/\.(jpe?g|png|webp|gif|avif)(?:[?#]|$)/i.test(url || '')) score += 2;

            const stable = value => String(value || '').split(/\s+/).filter(token =>
                /^[-_a-zA-Z][-_a-zA-Z0-9]{1,50}$/.test(token) &&
                !/^(css|sc|jsx?)-?[a-f0-9]{5,}$/i.test(token)
            );
            const classes = stable(image.className);
            const parentClasses = stable(image.parentElement?.className);
            const attributes = [...image.attributes].map(attr => attr.name)
                .filter(name => /^data-(page|document|reader)/i.test(name));
            const urlPattern = (url || '').replace(/\d+/g, '#');
            let sequenceIndex = null;
            try {
                let sequenceUrl = new URL(url);
                const proxied = sequenceUrl.searchParams.get('url');
                if (proxied) sequenceUrl = new URL(proxied, document.baseURI);
                const match = sequenceUrl.pathname.match(/(?:^|\/)(\d+)(?=\.[a-z0-9]+$)/i);
                if (match) sequenceIndex = Number(match[1]);
            } catch (_) {}
            return {position, url, width, height, score, decorative, classes,
                parentClasses, attributes, urlPattern,
                dataIndex: image.dataset.index ?? sequenceIndex};
        })
        """
    )


def _deduplicate(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in sorted(items, key=lambda row: row["position"]):
        if item.get("url") and item["url"] not in seen:
            seen.add(item["url"])
            result.append(item)
    return result


def _auto_group(candidates: list[dict], expected: int | None) -> tuple[list[dict], str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    descriptions: dict[str, str] = {}
    for item in candidates:
        if (
            not item.get("url")
            or item.get("decorative")
            or item.get("score", 0) <= -5
        ):
            continue
        for class_name in item.get("classes", []):
            key = f"class:{class_name}"
            groups[key].append(item)
            descriptions[key] = f"img.{class_name}"
        if item.get("classes"):
            joined = ".".join(item["classes"])
            key = f"classes:{joined}"
            groups[key].append(item)
            descriptions[key] = f"img.{joined}"
        for attribute in item.get("attributes", []):
            key = f"attr:{attribute}"
            groups[key].append(item)
            descriptions[key] = f"img[{attribute}]"
        if item.get("parentClasses"):
            parent = item["parentClasses"][0]
            key = f"parent:{parent}"
            groups[key].append(item)
            descriptions[key] = f".{parent} img"
        if item.get("urlPattern"):
            key = f"url:{item['urlPattern']}"
            groups[key].append(item)
            descriptions[key] = "motif d'URL répété"

    ranked: list[tuple[float, str, list[dict]]] = []
    for key, raw_items in groups.items():
        items = _deduplicate(raw_items)
        if len(items) < 2 and not (expected == 1 and len(items) == 1):
            continue
        scores = [item.get("score", 0) for item in items]
        rank = len(items) * 20 + sum(scores)
        patterns = Counter(
            str(item.get("urlPattern") or "") for item in items
        )
        if patterns:
            dominant_pattern_count = max(patterns.values())
            rank -= (len(items) - dominant_pattern_count) * 45
        if (
            key.startswith("url:")
            and expected
            and abs(len(items) - expected) >= max(3, round(expected * 0.03))
        ):
            # Un grand écart peut signaler un compteur de lecteur contaminé
            # par des vignettes ou contrôles, tandis qu'une famille d'URL
            # homogène reste une meilleure représentation des pages réelles.
            rank += 300
        if expected:
            if len(items) == expected:
                rank += 2000
            else:
                rank -= abs(len(items) - expected) * 15
        positions = [item["position"] for item in items]
        if positions == list(range(min(positions), max(positions) + 1)):
            rank += 20
        ranked.append((rank, key, items))

    if not ranked:
        raise RuntimeError(
            "Auto-détection ambiguë : aucun groupe fiable de pages n'a été trouvé. "
            "Utilisez --selector avec un sélecteur CSS."
        )
    _, key, selected = max(ranked, key=lambda row: row[0])
    return selected, descriptions[key]


def discover_pages(
    page, explicit_selector: str | None, expected: int | None
) -> tuple[list[dict], str]:
    manifest_pages = pages_from_manifest(page)
    if manifest_pages:
        return manifest_pages, "html-manifest"

    selector = normalize_selector_input(explicit_selector)
    if selector:
        selected = _deduplicate(collect_image_candidates(page, selector))
        source = selector
    elif page.locator("img[data-document-page]").count():
        selected = _deduplicate(collect_image_candidates(page, "img[data-document-page]"))
        source = "img[data-document-page]"
    else:
        candidates = collect_image_candidates(page, "img")
        try:
            selected, source = _auto_group(candidates, expected)
        except RuntimeError as exc:
            surfaces = inspect_render_surfaces(page)
            if (
                surfaces["canvas_count"]
                or surfaces["iframe_count"]
                or surfaces["reader_hint"]
            ):
                count = surfaces.get("accessible_page_count")
                count_text = (
                    f", {count} emplacement(s) accessible(s) annoncé(s)"
                    if count
                    else ""
                )
                raise RuntimeError(
                    "Lecteur canvas/PDF détecté "
                    f"({surfaces['canvas_count']} canvas, "
                    f"{surfaces['iframe_count']} iframe(s){count_text}). "
                    "Les pages originales ne sont pas exposées comme images : "
                    "extraction annulée pour éviter des logos ou des captures "
                    "basse qualité."
                ) from exc
            raise

    pages = [
        {
            "page": position,
            "url": item["url"],
            "source": source,
            **(
                {"document_index": item["dataIndex"]}
                if item.get("dataIndex") is not None
                else {}
            ),
        }
        for position, item in enumerate(selected, start=1)
    ]
    return pages, source
