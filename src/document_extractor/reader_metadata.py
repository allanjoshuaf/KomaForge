"""Observe reader network responses and derive publication page totals."""

from __future__ import annotations

import time
from urllib.parse import urlparse

from .detection import ExpectedCount


METADATA_REQUEST_TIMEOUT_MS = 45_000


def remember_browser_document(candidates: list[dict], response) -> None:
    """Mémorise une ressource documentaire chargée par le lecteur."""

    try:
        request = response.request
        content_type = response.headers.get("content-type", "").lower()
        disposition = response.headers.get("content-disposition", "").lower()
        if "application/pdf" in content_type or ".pdf" in disposition:
            document_format = "pdf"
        elif "application/epub+zip" in content_type or ".epub" in disposition:
            document_format = "epub"
        else:
            return
        if request.method != "GET":
            return
        if any(item.get("request") is request for item in candidates):
            return
        candidates.append(
            {
                "request": request,
                "response": response,
                "owner_page": request.frame.page,
                "document_format": document_format,
                "content_type": content_type,
                "content_disposition": disposition,
                "content_length": int(
                    response.headers.get("content-length", "0") or 0
                ),
                "accept_ranges": response.headers.get("accept-ranges", ""),
            }
        )
    except Exception:
        # Une réponse qui disparaît pendant une navigation ne doit jamais
        # interrompre l'extraction normale des images.
        return


def remember_reader_metadata(candidates: list[dict], response) -> None:
    """Mémorise les réponses JSON susceptibles d'annoncer le total des pages."""

    try:
        request = response.request
        content_type = response.headers.get("content-type", "").lower()
        if request.method != "GET" or "json" not in content_type:
            return
        candidates.append(
            {
                "response": response,
                "owner_page": request.frame.page,
                "source": urlparse(response.url).path,
            }
        )
    except Exception:
        return


def page_count_candidates(value, source: str, path: str = "root") -> list[dict]:
    """Find credible total-page fields in nested reader metadata."""

    found: list[dict] = []
    if isinstance(value, dict):
        normalized = {
            "".join(character for character in str(key).lower() if character.isalnum()):
            (key, item)
            for key, item in value.items()
        }
        for normalized_key, (key, item) in normalized.items():
            child_path = f"{path}.{key}"
            if (
                normalized_key
                in {
                    "pagecount",
                    "totalpages",
                    "totalpagecount",
                    "numberofpages",
                    "numpages",
                    "pagetotal",
                }
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
                and 0 < int(item) <= 100_000
            ):
                score = 95
                if "total" in normalized_key or "numberof" in normalized_key:
                    score += 3
                if any(token in source.lower() for token in ("page", "label", "pdf")):
                    score += 4
                labels = normalized.get("labels")
                if labels and isinstance(labels[1], list) and len(labels[1]) == int(item):
                    score += 10
                found.append(
                    {
                        "value": int(item),
                        "source": f"métadonnées réseau: {source} ({child_path})",
                        "score": score,
                    }
                )
            found.extend(page_count_candidates(item, source, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:1000]):
            found.extend(page_count_candidates(item, source, f"{path}[{index}]"))
    return found


def reader_publication_total(
    context, metadata_candidates: list[dict], page
) -> ExpectedCount | None:
    """Return the most credible page total observed for one reader page."""

    found: list[dict] = []
    for candidate in list(metadata_candidates):
        if candidate.get("owner_page") is not page:
            continue
        try:
            payload = candidate["response"].json()
        except Exception:
            try:
                request = candidate["response"].request
                headers = {
                    key: value
                    for key, value in request.all_headers().items()
                    if not key.startswith(":")
                    and key.lower()
                    not in {
                        "accept-encoding",
                        "connection",
                        "content-length",
                        "host",
                    }
                }
                replay = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=METADATA_REQUEST_TIMEOUT_MS,
                )
                payload = replay.json()
            except Exception:
                continue
        found.extend(
            page_count_candidates(payload, str(candidate.get("source") or "JSON"))
        )
    if not found:
        return None
    best = max(found, key=lambda item: (item["score"], item["value"]))
    return ExpectedCount(best["value"], best["source"], "élevée")


def wait_for_publication_total(
    context,
    metadata_candidates: list[dict],
    page,
    timeout_ms: int = 15_000,
) -> ExpectedCount | None:
    """Wait briefly for asynchronous metadata to announce a page total."""

    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        total = reader_publication_total(context, metadata_candidates, page)
        if total is not None:
            return total
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)
