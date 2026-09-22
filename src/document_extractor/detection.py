from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin


PAGE_TIMEOUT_MS = 90_000


@dataclass(frozen=True)
class ExpectedCount:
    value: int
    source: str
    confidence: str


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
                /\b(\d+)\s*pages?\b/i
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
        page.wait_for_timeout(800)
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
                page.wait_for_timeout(750)
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
                const label = normal([
                    button.textContent, button.value, button.id, button.name,
                    button.className, button.getAttribute('aria-label'),
                    button.getAttribute('title')
                ].join(' '));
                let score = 0;
                if (useful.test(label)) score += 12;
                if (contextWords.test(label)) score += 5;
                if (/show.?all/.test(label)) score += 6;
                results.push({kind: 'button', index, label: label.slice(0, 100), score});
            });
            results.sort((a, b) => b.score - a.score);
            return results[0] || null;
        }
        """
    )
    if not candidate:
        return None
    if candidate["kind"] == "button" and re.search(
        r"\b(fullscreen|full screen|plein ecran)\b", candidate.get("label", "")
    ):
        return None
    threshold = 10 if candidate["kind"] == "select" else 12
    if candidate["score"] < threshold:
        return None

    if candidate["kind"] == "select":
        control = page.locator("select").nth(candidate["index"])
        if not candidate.get("alreadyActive"):
            control.select_option(candidate["value"])
            page.wait_for_timeout(800)
        return {
            "action": f"select -> {candidate['label']} ({candidate['value']})",
            "source": "détection automatique",
            "score": candidate["score"],
        }

    controls = page.locator(
        'button, [role="button"], input[type="button"], input[type="radio"]'
    )
    controls.nth(candidate["index"]).click()
    page.wait_for_timeout(800)
    return {
        "action": f"clic -> {candidate['label']}",
        "source": "détection automatique",
        "score": candidate["score"],
    }


def hydrate_lazy_content(page, expected: int | None, max_steps: int = 400) -> dict:
    """Fait défiler le lecteur pour matérialiser les pages chargées à la demande."""
    stable_bottom = 0
    previous = None
    steps = 0
    for steps in range(1, max_steps + 1):
        state = page.evaluate(
            """
            () => ({
                imageCount: [...document.images].filter(img =>
                    img.currentSrc || img.src || img.dataset.src ||
                    img.dataset.lazySrc || img.dataset.original || img.dataset.url
                ).length,
                height: Math.max(document.body?.scrollHeight || 0,
                    document.documentElement?.scrollHeight || 0),
                y: window.scrollY,
                viewport: window.innerHeight
            })
            """
        )
        at_bottom = state["y"] + state["viewport"] >= state["height"] - 4
        signature = (state["imageCount"], state["height"])
        if at_bottom and signature == previous:
            stable_bottom += 1
        else:
            stable_bottom = 0
        if stable_bottom >= 3:
            break
        previous = signature
        page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 1.35, 600))")
        page.wait_for_timeout(75)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    return {"steps": steps, "images_seen": state["imageCount"]}


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
            return {position, url, width, height, score, classes,
                parentClasses, attributes, urlPattern,
                dataIndex: image.dataset.index ?? null};
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
        if not item.get("url") or item.get("score", 0) <= -5:
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
        selected, source = _auto_group(collect_image_candidates(page, "img"), expected)

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
