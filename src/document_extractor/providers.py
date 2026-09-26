from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse, urlunparse

from .detection import ExpectedCount, PAGE_TIMEOUT_MS


@dataclass(frozen=True)
class ChapterDiscovery:
    index: int
    number: str
    title: str
    source_url: str
    pages: list[dict]
    expected: ExpectedCount | None = None


@dataclass(frozen=True)
class ProviderDiscovery:
    name: str
    publication_type: str
    title: str
    chapters: list[ChapterDiscovery]
    allowed_hosts: set[str]

    @property
    def pages(self) -> list[dict]:
        """Vue aplatie conservée pour les consommateurs qui inspectent une publication."""
        return [page for chapter in self.chapters for page in chapter.pages]


def _calameo_book_code(url: str) -> str | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in {"calameo.com", "www.calameo.com"}:
        return None
    match = re.fullmatch(r"/read/([A-Za-z0-9_-]+)/*", parsed.path)
    return match.group(1) if match else None


def build_calameo_pages(
    content: dict,
    loaded_urls: list[str],
    source_url: str = "",
) -> ProviderDiscovery:
    document = content.get("document") or {}
    total = int(document.get("pages") or 0)
    if total <= 0 or total > 100_000:
        raise RuntimeError("Calaméo n'a pas fourni un nombre de pages valide.")

    key = str(content.get("key") or "")
    secured_svg = ((content.get("domains") or {}).get("secured") or {}).get("svg")
    secured_host = (urlparse(str(secured_svg or "")).hostname or "").lower()
    if not key or not secured_host:
        raise RuntimeError("Calaméo n'a pas fourni de domaine SVG sécurisé.")

    source = None
    expected_path = re.compile(rf"/{re.escape(key)}/p\d+\.svgz$")
    for raw_url in loaded_urls:
        parsed = urlparse(raw_url)
        if (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == secured_host
            and expected_path.fullmatch(parsed.path)
            and parsed.query
        ):
            source = parsed
            break
    if source is None:
        raise RuntimeError(
            "Calaméo n'a pas encore exposé une page SVGZ signée et vérifiable."
        )

    pages = [
        {
            "page": number,
            "url": urlunparse(
                (
                    "https",
                    source.netloc,
                    f"/{quote(key, safe='')}/p{number}.svgz",
                    "",
                    source.query,
                    "",
                )
            ),
            "source": "profil-calameo",
        }
        for number in range(1, total + 1)
    ]
    title = str(content.get("name") or content.get("title") or "Document Calaméo").strip()
    return ProviderDiscovery(
        name="calameo",
        publication_type="book",
        title=title,
        chapters=[
            ChapterDiscovery(
                index=1,
                number="1",
                title=title,
                source_url=source_url,
                pages=pages,
                expected=ExpectedCount(
                    total,
                    "manifeste public Calaméo",
                    "élevée",
                ),
            )
        ],
        allowed_hosts={secured_host},
    )


def discover_provider(context, page, url: str) -> ProviderDiscovery | None:
    book_code = _calameo_book_code(url)
    if book_code is None:
        return None

    endpoint = (
        "https://d.calameo.com/pinwheel/viewer/book/get?bkcode="
        + quote(book_code, safe="")
    )
    response = context.request.get(
        endpoint,
        headers={"Referer": url},
        timeout=PAGE_TIMEOUT_MS,
        fail_on_status_code=False,
    )
    if not response.ok:
        raise RuntimeError(f"Manifeste Calaméo inaccessible : HTTP {response.status}")
    payload = response.json()
    if payload.get("status") != "ok" or not isinstance(payload.get("content"), dict):
        raise RuntimeError("Réponse inattendue du manifeste Calaméo.")

    deadline = time.monotonic() + PAGE_TIMEOUT_MS / 1000
    last_error: RuntimeError | None = None
    while time.monotonic() < deadline:
        loaded_urls = page.evaluate(
            """
            () => {
                const images = [...document.querySelectorAll('img')]
                    .map(image => image.currentSrc || image.src)
                    .filter(Boolean);
                const resources = performance.getEntriesByType('resource')
                    .map(entry => entry.name)
                    .filter(Boolean);
                return [...new Set([...images, ...resources])];
            }
            """
        )
        try:
            return build_calameo_pages(payload["content"], loaded_urls, url)
        except RuntimeError as exc:
            if "pas encore exposé" not in str(exc):
                raise
            last_error = exc
        page.wait_for_timeout(250)
    raise last_error or RuntimeError(
        "Calaméo n'a pas exposé de page SVGZ signée dans le délai prévu."
    )
