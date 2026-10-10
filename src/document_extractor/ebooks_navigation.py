from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse



def is_ebooks_product_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    return host in {"ebooks.com", "www.ebooks.com"} and bool(
        re.search(r"/(?:[a-z]{2}-[a-z]{2}/)?book/\d+(?:/|$)", parsed.path)
    )


def _ebooks_reader_url(value: object) -> str | None:
    """Accepte uniquement une URL HTTPS du lecteur officiel eBooks.com."""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "reader.ebooks.com"
        or not parsed.path.startswith("/preview")
    ):
        return None
    return value.strip()


def _ebooks_preview_controls(page) -> tuple[dict | None, list[dict]]:
    """Collect current controls; a frontend rerender can replace old markers."""
    candidates = page.evaluate(
        r"""
        () => {
            const normal = value => String(value || '').normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '').toLowerCase()
                .replace(/\s+/g, ' ').trim();
            const exact = /^(?:preview|tap to preview|read sample|look inside|read online|read now|apercu|lire un extrait|lire en ligne)$/;
            const controls = [...document.querySelectorAll(
                'a, button, [role="button"], img[alt], [aria-label]'
            )];
            const candidates = [];
            const seen = new Set();
            for (const node of controls) {
                const target = node.matches('a, button, [role="button"]')
                    ? node
                    : node.closest('a, button, [role="button"]');
                if (!target || seen.has(target)) continue;
                seen.add(target);
                const rect = target.getBoundingClientRect();
                const style = getComputedStyle(target);
                if (rect.width <= 0 || rect.height <= 0 ||
                    style.display === 'none' || style.visibility === 'hidden') continue;
                const primaryText = [...target.querySelectorAll('span')]
                    .find(span => !span.classList.contains('sr-only') &&
                        (span.textContent || '').trim())?.textContent;
                const label = normal(
                    target.getAttribute('aria-label') || node.getAttribute('alt') ||
                    primaryText || target.textContent || target.getAttribute('title')
                );
                if (!exact.test(label) && !/\bpreview\b/.test(label)) continue;
                const href = target.href || target.getAttribute('data-href') ||
                    target.getAttribute('data-url') || '';
                const marker = `reader-entry-${Date.now()}-${Math.random().toString(36).slice(2)}`;
                target.setAttribute('data-komaforge-reader-entry', marker);
                candidates.push({marker, label, href});
                if (candidates.length >= 8) break;
            }
            return candidates;
        }
        """
    )
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return None, []

    clickable_candidates: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        href = str(candidate.get("href") or "")
        direct_url = _ebooks_reader_url(urljoin(page.url, href))
        if direct_url:
            return {"url": direct_url, "action": candidate["label"]}, []
        # An ordinary link such as the footer's "Read online" help page is
        # not a launch control and must never be clicked speculatively.
        if href:
            continue
        clickable_candidates.append(candidate)
    return None, clickable_candidates


def discover_linked_reader(context, page) -> dict | None:
    """Ouvre une prévisualisation explicitement proposée par une page produit."""
    if not is_ebooks_product_url(page.url):
        return None
    # DOMContentLoaded does not imply that the product's preview control exists
    # yet. Wait briefly for that explicit control, never for a guessed URL.
    readiness_deadline = time.monotonic() + 5
    while True:
        direct_entry, clickable_candidates = _ebooks_preview_controls(page)
        if direct_entry:
            return direct_entry
        if clickable_candidates:
            break
        if time.monotonic() >= readiness_deadline:
            return None
        page.wait_for_timeout(250)

    launched_urls: list[str] = []

    def remember_preview_launch(response) -> None:
        try:
            parsed = urlparse(response.url)
            if (
                (parsed.hostname or "").casefold()
                != "reader-backend.ebooks.com"
                or parsed.path.rstrip("/").casefold()
                != "/api/reader-instance/preview-launch"
                or not response.ok
            ):
                return
            payload = response.json()
            launched = _ebooks_reader_url(payload.get("previewUrl"))
            if payload.get("ok") and launched:
                launched_urls.append(launched)
        except Exception:
            return

    page.on("response", remember_preview_launch)

    try:
        deadline = time.monotonic() + 30
        # The preview-launch endpoint can ignore the first click immediately
        # after its access check has cleared. A second bounded pass uses the
        # current explicit Preview controls without guessing an endpoint or URL.
        for _round in range(2):
            if _round:
                direct_entry, refreshed_candidates = _ebooks_preview_controls(page)
                if direct_entry:
                    return direct_entry
                if refreshed_candidates:
                    clickable_candidates = refreshed_candidates
            for candidate in clickable_candidates:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                control = page.locator(
                    f'[data-komaforge-reader-entry="{candidate["marker"]}"]'
                ).first
                try:
                    try:
                        control.click(timeout=min(5_000, max(1, int(remaining * 1_000))),
                                      no_wait_after=True)
                    except Exception:
                        if time.monotonic() >= deadline:
                            break
                        control.evaluate("node => node.click()")
                except Exception:
                    continue

                attempt_deadline = min(deadline, time.monotonic() + 10)
                while time.monotonic() < attempt_deadline:
                    if launched_urls:
                        return {"url": launched_urls[-1], "action": candidate["label"]}
                    active_urls = [
                        active.url
                        for active in context.pages
                        if not active.is_closed()
                    ]
                    active_urls.extend(frame.url for frame in page.frames)
                    for raw_url in active_urls:
                        reader_url = _ebooks_reader_url(raw_url)
                        if reader_url:
                            return {"url": reader_url, "action": candidate["label"]}
                    page.wait_for_timeout(250)
                if time.monotonic() >= deadline:
                    break
            if time.monotonic() >= deadline:
                break
    finally:
        try:
            page.remove_listener("response", remember_preview_launch)
        except Exception:
            pass
    return {
        "url": None,
        "action": clickable_candidates[0]["label"],
        "error": "aucun bouton de prévisualisation n'a fourni d'URL de lecteur",
    }
