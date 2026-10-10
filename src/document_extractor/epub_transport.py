"""Browser-session transport and validation for EPUB resources."""

from __future__ import annotations
from .diagnostic_ui import diagnostic_print as print, diagnostic_input as input

from .formats import inspect_epub
from .terminal_ui import rt


EPUB_REQUEST_TIMEOUT_MS = 180_000
EPUB_BODY_REUSE_MAX_BYTES = 8 * 1024 * 1024


def fetch_browser_epub(
    context,
    candidate: dict,
    language: str = "fr",
) -> tuple[bytes, dict]:
    """Récupère et valide l'EPUB observé dans la session réelle du lecteur."""

    request = candidate["request"]
    data = b""
    observed_response = candidate.get("response")
    content_length = int(candidate.get("content_length") or 0)
    if observed_response is not None and 0 < content_length <= EPUB_BODY_REUSE_MAX_BYTES:
        try:
            if not observed_response.ok:
                raise RuntimeError(
                    f"Ressource EPUB inaccessible : HTTP {observed_response.status}"
                )
            data = observed_response.body()
            if data:
                print(rt(language, "epub_loaded"))
        except Exception:
            data = b""

    if not data:
        headers = {
            key: value
            for key, value in request.all_headers().items()
            if not key.startswith(":")
            and key.lower()
            not in {"accept-encoding", "connection", "content-length", "host", "range"}
        }
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=EPUB_REQUEST_TIMEOUT_MS,
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Ressource EPUB inaccessible : HTTP {response.status}"
                    )
                data = response.body()
                break
            except Exception as exc:
                last_error = exc
                print(f"Récupération EPUB {attempt}/2 échouée : {exc}")
        if not data:
            raise RuntimeError(
                "La ressource EPUB n'a pas pu être récupérée après deux "
                f"tentatives : {last_error}"
            )
    try:
        info = inspect_epub(data)
    except Exception as exc:
        raise RuntimeError(f"La ressource EPUB détectée est invalide : {exc}") from exc
    return data, info
