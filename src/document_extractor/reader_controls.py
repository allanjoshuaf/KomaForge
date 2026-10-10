from __future__ import annotations

import re
import time
from urllib.parse import urlparse


from .detection_shared import PAGE_TIMEOUT_MS, INTERSTITIAL_PATTERN, ExpectedCount

def dismiss_cookie_consent(page) -> dict | None:
    """Ferme les bandeaux connus en refusant les cookies non essentiels."""
    selectors = (
        "#CybotCookiebotDialogBodyButtonDecline",
        "#onetrust-reject-all-handler",
        "#didomi-notice-disagree-button",
        '[data-testid="uc-deny-all-button"]',
    )
    host = (urlparse(page.url).hostname or "").casefold()
    wait_for_late_banner = host.endswith("calameo.com")
    if not wait_for_late_banner:
        try:
            wait_for_late_banner = bool(
                page.locator(
                    'script[src*="cookiebot" i], script[src*="onetrust" i], '
                    'script[src*="didomi" i], script[src*="usercentrics" i]'
                ).count()
            )
        except Exception:
            pass

    deadline = time.monotonic() + (15 if wait_for_late_banner else 0)
    while True:
        for selector in selectors:
            control = page.locator(selector).first
            try:
                if control.count() == 0 or not control.is_visible(timeout=500):
                    continue
                label = " ".join(
                    (control.inner_text(timeout=1_000) or "").split()
                )
                try:
                    control.click(timeout=10_000)
                except Exception:
                    control.evaluate("node => node.click()")
                try:
                    control.wait_for(state="hidden", timeout=10_000)
                except Exception:
                    pass
                return {
                    "action": (
                        "refus des cookies non essentiels -> "
                        f"{label or selector}"
                    ),
                    "source": "bandeau de consentement",
                }
            except Exception:
                continue
        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(250)
    return None


def access_interstitial_state(page) -> dict:
    data = page.evaluate(
        r"""
        () => ({
            title: document.title || '',
            body: (document.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 3000)
        })
        """
    )
    text = f"{data.get('title', '')} {data.get('body', '')}"
    return {
        "active": bool(INTERSTITIAL_PATTERN.search(text)),
        "title": " ".join(str(data.get("title") or "").split()),
    }


def wait_for_access_interstitial(page, timeout_ms: int = 45_000) -> dict:
    """Attend la fin naturelle d'un écran de vérification sans le contourner."""

    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        try:
            first = access_interstitial_state(page)
            break
        except Exception as exc:
            message = str(exc).casefold()
            if (
                "execution context was destroyed" not in message
                and "because of a navigation" not in message
            ):
                raise
            if time.monotonic() >= deadline:
                raise
            page.wait_for_timeout(250)
    if not first["active"]:
        return {**first, "encountered": False, "passed": True, "waited_ms": 0}

    stable_since: float | None = None
    current = first
    while time.monotonic() < deadline:
        page.wait_for_timeout(250)
        try:
            current = access_interstitial_state(page)
        except Exception as exc:
            message = str(exc).casefold()
            if (
                "execution context was destroyed" in message
                or "because of a navigation" in message
            ):
                stable_since = None
                continue
            raise
        if current["active"]:
            stable_since = None
            continue
        if stable_since is None:
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= 1.5:
            return {
                **current,
                "encountered": True,
                "passed": True,
                "waited_ms": round((timeout_ms / 1000 - (deadline - time.monotonic())) * 1000),
            }
    return {
        **current,
        "encountered": True,
        "passed": False,
        "waited_ms": timeout_ms,
    }


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

            const indexedPages = [...document.querySelectorAll('[id^="outer_page_"]')]
                .map(node => Number.parseInt(node.id.match(/^outer_page_(\d+)$/)?.[1], 10))
                .filter(Number.isFinite)
                .sort((a, b) => a - b);
            if (indexedPages.length >= 2 && indexedPages[0] === 1 &&
                indexedPages.every((value, index) => value === index + 1)) {
                add(indexedPages.at(-1), 'conteneurs de pages indexés', 100);
            }

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
                if (strong.test(displayLabel)) score += 12;
                else if (useful.test(displayLabel) && contextWords.test(searchable)) score += 12;
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
            r"back to top|next|previous|precedent|suivant|"
            r"show full (?:title|description|details|text))\b",
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
    indexed_containers = page.evaluate(
        r"""
        () => [...document.querySelectorAll('[id^="outer_page_"]')]
            .map(node => ({
                id: node.id,
                index: Number.parseInt(node.id.match(/^outer_page_(\d+)$/)?.[1], 10)
            }))
            .filter(item => Number.isFinite(item.index))
            .sort((a, b) => a.index - b.index)
        """
    )
    if (
        isinstance(indexed_containers, list)
        and len(indexed_containers) >= 2
        and indexed_containers[0]["index"] == 1
        and all(
            item["index"] == position
            for position, item in enumerate(indexed_containers, start=1)
        )
    ):
        selected = indexed_containers[:max_steps]
        captured = page.evaluate(
            r"""
            async items => {
                const captured = [];
                const delay = milliseconds => new Promise(
                    resolve => setTimeout(resolve, milliseconds)
                );
                const resourceFor = item => {
                    const container = document.getElementById(item.id);
                    if (!container) return null;
                    const images = [...container.querySelectorAll('img')]
                        .map(image => ({
                            url: image.dataset.src || image.dataset.lazySrc ||
                                image.dataset.original || image.dataset.url ||
                                image.getAttribute('data-lazy') || image.currentSrc ||
                                image.src || '',
                            width: image.naturalWidth || Number(image.getAttribute('width')) || 0,
                            height: image.naturalHeight || Number(image.getAttribute('height')) || 0
                        }))
                        .filter(image => image.url &&
                            !/(loading|placeholder|spinner|transparent|blank)(?:img)?\.(?:gif|png|webp|svg)(?:[?#]|$)/i
                                .test(image.url))
                        .sort((a, b) => (b.width * b.height) - (a.width * a.height));
                    if (!images.length) return null;
                    return {page: item.index, position: item.index - 1,
                        dataIndex: item.index, url: images[0].url,
                        width: images[0].width, height: images[0].height};
                };
                const scrollToItem = item => {
                    const container = document.getElementById(item.id);
                    if (!container) return;
                    const top = container.getBoundingClientRect().top + window.scrollY;
                    window.scrollTo(0, Math.max(0, top - (window.innerHeight / 3)));
                };
                for (const item of items) {
                    scrollToItem(item);
                    await delay(80);
                    let resource = resourceFor(item);
                    if (!resource) {
                        await delay(80);
                        resource = resourceFor(item);
                    }
                    if (resource) captured.push(resource);
                }
                const capturedPages = new Set(captured.map(item => item.page));
                for (const item of items.filter(item => !capturedPages.has(item.index))) {
                    scrollToItem(item);
                    await delay(240);
                    let resource = resourceFor(item);
                    if (!resource) {
                        await delay(240);
                        resource = resourceFor(item);
                    }
                    if (resource) captured.push(resource);
                }
                captured.sort((a, b) => a.page - b.page);
                window.__komaforgeIndexedPageResources = captured;
                window.scrollTo(0, 0);
                return captured;
            }
            """,
            selected,
        )
        time.sleep(0.25)
        return {
            "steps": len(selected),
            "images_seen": len(captured),
            "images_ready": len(captured),
        }

    stable_bottom = 0
    stable_expected = 0
    stable_progress = 0
    previous = None
    previous_content = None
    reached_bottom = False
    steps = 0
    for steps in range(1, max_steps + 1):
        state = page.evaluate(
            r"""
            () => {
                const images = [...document.images];
                const urls = images.map(img => img.dataset.src ||
                    img.dataset.lazySrc || img.dataset.original || img.dataset.url ||
                    img.getAttribute('data-lazy') || img.currentSrc || img.src || '');
                const unresolved = urls.map((url, index) => ({url, index}))
                    .filter(item => !item.url ||
                        /(loading|placeholder|spinner|transparent|blank)(?:img)?\.(?:gif|png|webp|svg)(?:[?#]|$)/i
                            .test(item.url));
                const visibleUnresolved = unresolved.filter(item => {
                    const image = images[item.index];
                    const style = getComputedStyle(image);
                    const rect = image.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                });
                return {
                    imageCount: urls.filter(Boolean).length,
                    resolvedCount: urls.length - unresolved.length,
                    uniqueCount: new Set(urls.filter(Boolean)).size,
                    unresolved: visibleUnresolved.map(item => item.index),
                    height: Math.max(document.body?.scrollHeight || 0,
                        document.documentElement?.scrollHeight || 0),
                    y: window.scrollY,
                    viewport: window.innerHeight
                };
            }
            """
        )
        at_bottom = state["y"] + state["viewport"] >= state["height"] - 4
        content_signature = (
            state["resolvedCount"],
            state["uniqueCount"],
            state["height"],
        )
        signature = (
            *content_signature,
            state["y"],
        )
        reached_bottom = reached_bottom or at_bottom
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
        if content_signature == previous_content:
            stable_progress += 1
        else:
            stable_progress = 0
        if stable_bottom >= 3 and steps >= minimum_steps:
            break
        if (
            reached_bottom
            and stable_progress >= minimum_steps
            and steps >= minimum_steps
        ):
            break
        previous = signature
        previous_content = content_signature
        if state["unresolved"]:
            target = state["unresolved"][(steps - 1) % len(state["unresolved"])]
            page.evaluate(
                "index => document.images[index]?.scrollIntoView({block: 'center'})",
                target,
            )
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
