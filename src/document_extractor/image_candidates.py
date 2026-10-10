from __future__ import annotations

import base64
from collections import Counter, defaultdict
from urllib.parse import urljoin


from .detection_shared import PAGE_TIMEOUT_MS

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
            const decorationText = [image.id, image.className, image.alt,
                image.getAttribute('role'), image.parentElement?.id,
                image.parentElement?.className].join(' ').toLowerCase();
            const decorative = /(logo|icon|avatar|emoji|banner|advert|sponsor|thumbnail|hero|favicon|mascot|notification|recommend|chapter.?slider|call.?to.?action|(?:^|\W)cta(?:\W|$))/
                .test(decorationText) ||
                /\/inc\/img\/(?:cta|chapter-providers)\/|\/manga\/primary\/|\/mascot\.(?:png|webp|jpe?g)/i
                .test(url || '');
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


def collect_indexed_page_container_candidates(page) -> list[dict]:
    """Return resources captured while walking numbered page containers."""

    resources = page.evaluate(
        "() => window.__komaforgeIndexedPageResources || []"
    )
    if not isinstance(resources, list):
        return []
    return [
        item
        for item in resources
        if isinstance(item, dict)
        and isinstance(item.get("url"), str)
        and item["url"].strip()
    ]


def collect_chapter_reader_manifest(page) -> list[dict]:
    """Lit la liste ordonnée que le lecteur ``ChapterReader`` utilise déjà.

    Ce lecteur n'affiche qu'une image à la fois. Son initialisation charge
    cependant un manifeste JSON de chapitre : cette liste est plus complète
    et plus rapide à vérifier qu'une succession de clics sur ``Suivant``.
    """
    raw_items = page.evaluate(
        r"""
        async () => {
            const anchor = document.querySelector('.ChapterReader');
            if (!anchor) return [];
            const slug = anchor.dataset.mangaslug;
            const chapter = anchor.dataset.chapter;
            if (!slug || !chapter) return [];
            const endpoint = `/api/manga/chapter/${encodeURIComponent(slug)}/${encodeURIComponent(chapter)}`;
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 15000);
            try {
                const response = await fetch(endpoint, {
                    credentials: 'same-origin',
                    headers: {'Accept': 'application/json'},
                    signal: controller.signal,
                });
                if (!response.ok) return [];
                const payload = await response.json();
                if (payload?.status !== 'ok' || !Array.isArray(payload?.data?.images)) {
                    return [];
                }
                return payload.data.images.map((item, index) => {
                    const value = typeof item === 'string'
                        ? item
                        : item?.url || item?.src || item?.image ||
                          item?.imageUrl || item?.file || item?.path || '';
                    if (!value) return null;
                    let url;
                    try { url = new URL(value, document.baseURI).href; }
                    catch (_) { return null; }
                    if (!/^https?:$/i.test(new URL(url).protocol)) return null;
                    return {
                        url,
                        position: index,
                        dataIndex: index,
                        width: Number(item?.width || 900),
                        height: Number(item?.height || 1350),
                        score: 30,
                        decorative: false,
                    };
                }).filter(Boolean);
            } catch (_) {
                return [];
            } finally {
                clearTimeout(timeout);
            }
        }
        """
    )
    if not isinstance(raw_items, list) or len(raw_items) < 2:
        return []
    selected = _deduplicate(raw_items)
    # Un manifeste qui contient des doublons ou des entrées invalides n'est
    # pas une preuve fiable du nombre total de pages.
    if len(selected) != len(raw_items):
        return []
    return selected


def collect_virtual_blob_reader_candidates(page) -> list[dict]:
    """Parcourt un lecteur virtualisé et conserve ses WebP déjà décodés.

    Le compteur du site représente des écrans (souvent doubles), pas le
    nombre de fichiers. Le lecteur virtualise aussi le DOM et révoque les URL
    ``blob:`` des pages éloignées. Le script d'initialisation garde une
    référence aux Blob originaux afin de préserver exactement leurs octets.
    """
    selector = 'img[src^="blob:"][alt^="page_"]'
    try:
        if page.locator(selector).count() < 2 or not page.evaluate(
            "window.__komaforgeBlobStore instanceof Map"
        ):
            return []
    except Exception:
        return []

    snapshot_script = r"""
    () => {
        const blobs = window.__komaforgeBlobStore;
        const pages = window.__komaforgePageBlobStore;
        if (!(blobs instanceof Map) || !(pages instanceof Map)) return null;
        const images = [...document.querySelectorAll(
            'img[src^="blob:"][alt^="page_"]'
        )];
        let readyCount = 0;
        for (const image of images) {
            const match = (image.alt || '').match(/^page_(\d+)$/);
            const blob = blobs.get(image.src);
            if (match && blob instanceof Blob && image.naturalWidth > 0 &&
                image.naturalHeight > 0) {
                pages.set(Number(match[1]), blob);
                readyCount += 1;
            }
        }
        const counter = (document.body?.innerText || '').match(
            /(?:^|\s)(\d+)\s*\/\s*(\d+)(?:\s|$)/
        );
        return {
            current: counter ? Number(counter[1]) : null,
            total: counter ? Number(counter[2]) : null,
            pageCount: pages.size,
            visibleCount: images.length,
            readyCount,
        };
    }
    """

    def stable_snapshot() -> dict | None:
        previous_count = -1
        stable = 0
        state = None
        for _ in range(80):
            state = page.evaluate(snapshot_script)
            if not isinstance(state, dict):
                return None
            count = int(state.get("pageCount") or 0)
            ready_count = int(state.get("readyCount") or 0)
            visible_count = int(state.get("visibleCount") or 0)
            all_ready = visible_count == 0 or ready_count == visible_count
            if count == previous_count and all_ready:
                stable += 1
                if stable >= 3:
                    return state
            else:
                stable = 0
                previous_count = count
            page.wait_for_timeout(250)
        if state:
            ready = int(state.get("readyCount") or 0)
            visible = int(state.get("visibleCount") or 0)
            if visible == 0 or ready == visible:
                return state
        return None

    state = stable_snapshot()
    if (
        not state
        or not isinstance(state.get("current"), int)
        or not isinstance(state.get("total"), int)
        or state["current"] < 1
        or state["total"] < state["current"]
    ):
        return []

    screen_total = state["total"]
    while state["current"] < screen_total:
        previous = state["current"]
        progressed = False
        for key in ("ArrowLeft", "ArrowRight"):
            page.keyboard.press(key)
            try:
                page.wait_for_function(
                    r"""
                    previous => {
                        const match = (document.body?.innerText || '').match(
                            /(?:^|\s)(\d+)\s*\/\s*(\d+)(?:\s|$)/
                        );
                        return match && Number(match[1]) > previous;
                    }
                    """,
                    arg=previous,
                    timeout=8_000,
                )
                progressed = True
                break
            except Exception:
                continue
        if not progressed:
            return []
        state = stable_snapshot()
        if not state or state.get("current", 0) <= previous:
            return []

    raw_items = page.evaluate(
        r"""
        async () => {
            const pages = window.__komaforgePageBlobStore;
            if (!(pages instanceof Map)) return [];
            const encode = blob => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onerror = () => reject(reader.error);
                reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
                reader.readAsDataURL(new Blob([blob], {type: 'image/webp'}));
            });
            return Promise.all([...pages.entries()]
                .sort((left, right) => left[0] - right[0])
                .map(async ([index, blob]) => ({
                    index,
                    size: blob.size,
                    base64: await encode(blob),
                })));
        }
        """
    )
    if not isinstance(raw_items, list) or len(raw_items) < 2:
        return []

    indices = [item.get("index") for item in raw_items]
    if indices != list(range(len(raw_items))):
        return []

    selected: list[dict] = []
    try:
        for item in raw_items:
            data = base64.b64decode(item["base64"], validate=True)
            if (
                len(data) != int(item["size"])
                or not data.startswith(b"RIFF")
                or data[8:12] != b"WEBP"
            ):
                return []
            index = int(item["index"])
            selected.append(
                {
                    "url": f"browser-blob://reader/page-{index + 1:04d}.webp",
                    "position": index,
                    "dataIndex": index,
                    "width": 900,
                    "height": 1350,
                    "score": 30,
                    "decorative": False,
                    "_embedded_data": data,
                    "_embedded_content_type": "image/webp",
                }
            )
    except (KeyError, TypeError, ValueError):
        return []

    print(
        "Lecteur virtualisé : "
        f"{len(selected)} page(s) originale(s) sur {screen_total} écran(s)"
    )
    return selected


def collect_paginated_reader_candidates(page) -> list[dict]:
    """Parcourt un lecteur qui remplace une unique image avec Suivant.

    Le couple de classes ``ChapterReader`` est volontairement exigé : cliquer
    un bouton Suivant générique pourrait changer de chapitre, ouvrir une
    recommandation ou quitter le document.
    """
    image_selector = ".ChapterReader--readerArea img"
    next_selector = ".ChapterReader--nextButton:visible"
    if (
        page.locator(image_selector).count() != 1
        or page.locator(next_selector).count() == 0
    ):
        return []

    source_url = page.url
    selected: list[dict] = []
    seen: set[str] = set()
    end_confirmed = False
    for index in range(10_000):
        current = collect_image_candidates(page, image_selector)
        if len(current) != 1:
            break
        item = current[0]
        resource_url = str(item.get("url") or "")
        if (
            not resource_url
            or resource_url in seen
            or item.get("decorative")
            or item.get("score", 0) < 5
            or item.get("width", 0) < 400
            or item.get("height", 0) < 500
        ):
            break
        item["position"] = index
        selected.append(item)
        seen.add(resource_url)

        control = page.locator(next_selector).first
        if control.count() == 0 or control.is_disabled():
            end_confirmed = True
            break
        try:
            control.click(timeout=10_000, no_wait_after=True)
            page.wait_for_function(
                """
                previous => {
                    const image = document.querySelector(
                        '.ChapterReader--readerArea img'
                    );
                    return image && (image.currentSrc || image.src) !== previous;
                }
                """,
                arg=resource_url,
                timeout=20_000,
            )
        except Exception:
            # Certains lecteurs laissent Suivant actif sur leur dernière page.
            # Après un délai complet, une source et une URL de document toutes
            # deux inchangées constituent notre confirmation de fin.
            try:
                current_url = page.locator(image_selector).get_attribute("src")
            except Exception:
                return []
            if page.url != source_url or not current_url:
                return []
            current_url = urljoin(page.url, current_url)
            if current_url == resource_url:
                end_confirmed = True
                break
            continue
        if page.url != source_url:
            return []

    # Sans fin confirmée, une panne ou un chargement lent ne doit jamais être
    # présenté comme un chapitre complet.
    if len(selected) < 2 or not end_confirmed:
        return []
    for index, item in enumerate(selected):
        item["dataIndex"] = index
    return selected


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
