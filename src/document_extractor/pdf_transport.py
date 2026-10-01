"""Browser-session transport and validation for PDF resources."""

from __future__ import annotations

from .pdf_structure import inspect_detached_page_trees


PDF_REQUEST_TIMEOUT_MS = 180_000
PDF_RANGE_TIMEOUT_MS = 60_000
PDF_RANGE_CHUNK_BYTES = 4 * 1024 * 1024
PDF_BODY_REUSE_MAX_BYTES = 8 * 1024 * 1024


def fetch_pdf_in_ranges(context, request, headers: dict, total: int) -> bytes:
    """Télécharge un gros PDF par segments vérifiés dans la même session."""

    chunks: list[bytes] = []
    starts = list(range(0, total, PDF_RANGE_CHUNK_BYTES))
    for position, start in enumerate(starts, 1):
        end = min(start + PDF_RANGE_CHUNK_BYTES - 1, total - 1)
        ranged_headers = {**headers, "range": f"bytes={start}-{end}"}
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=ranged_headers,
                    timeout=PDF_RANGE_TIMEOUT_MS,
                )
                body = response.body()
                if response.status == 200 and start == 0 and len(body) == total:
                    print("Récupération PDF : le serveur a renvoyé le fichier complet")
                    return body
                if response.status != 206:
                    raise RuntimeError(
                        f"HTTP {response.status} au lieu de 206 pour les octets "
                        f"{start}-{end}"
                    )
                expected_size = end - start + 1
                if len(body) != expected_size:
                    raise RuntimeError(
                        f"segment {start}-{end} tronqué : "
                        f"{len(body)}/{expected_size} octets"
                    )
                chunks.append(body)
                print(
                    f"Récupération PDF : segment {position}/{len(starts)} "
                    f"({end + 1}/{total} octets)"
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise RuntimeError(
                        f"Échec du segment PDF {start}-{end} après deux "
                        f"tentatives : {last_error}"
                    ) from exc
        else:
            raise RuntimeError(str(last_error))
    data = b"".join(chunks)
    if len(data) != total:
        raise RuntimeError(f"PDF assemblé incomplet : {len(data)}/{total} octets.")
    return data


def fetch_browser_pdf(context, candidate: dict) -> tuple[bytes, int, dict]:
    """Récupère le PDF observé, puis le rejoue seulement si nécessaire."""

    request = candidate["request"]
    data = b""
    content_type = str(candidate.get("content_type") or "").lower()
    content_length = int(candidate.get("content_length") or 0)
    observed_response = candidate.get("response")
    if (
        observed_response is not None
        and 0 < content_length <= PDF_BODY_REUSE_MAX_BYTES
    ):
        try:
            if not observed_response.ok:
                raise RuntimeError(
                    f"Ressource PDF inaccessible : HTTP {observed_response.status}"
                )
            data = observed_response.body()
            content_type = observed_response.headers.get(
                "content-type", content_type
            ).lower()
            if data:
                print("Ressource PDF : réponse déjà chargée par le navigateur")
        except Exception:
            data = b""

    headers = {
        key: value
        for key, value in request.all_headers().items()
        if not key.startswith(":")
        and key.lower()
        not in {"accept-encoding", "connection", "content-length", "host", "range"}
    }
    if (
        not data
        and content_length > PDF_BODY_REUSE_MAX_BYTES
        and str(candidate.get("accept_ranges") or "").lower() == "bytes"
    ):
        data = fetch_pdf_in_ranges(context, request, headers, content_length)

    if not data:
        headers = {
            key: value
            for key, value in headers.items()
            if not key.startswith(":")
            and key.lower()
            not in {"accept-encoding", "connection", "content-length", "host"}
        }
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = context.request.fetch(
                    request.url,
                    method="GET",
                    headers=headers,
                    timeout=PDF_REQUEST_TIMEOUT_MS,
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Ressource PDF inaccessible : HTTP {response.status}"
                    )
                data = response.body()
                content_type = response.headers.get(
                    "content-type", content_type
                ).lower()
                break
            except Exception as exc:
                last_error = exc
                print(f"Récupération PDF {attempt}/2 échouée : {exc}")
        if not data:
            raise RuntimeError(
                "La ressource PDF n'a pas pu être récupérée après deux "
                f"tentatives : {last_error}"
            )
    if "application/pdf" not in content_type and not data.startswith(b"%PDF-"):
        raise RuntimeError(
            "La ressource documentaire détectée n'est pas un PDF valide."
        )
    if not data.startswith(b"%PDF-"):
        raise RuntimeError("Le lecteur a renvoyé un PDF vide ou invalide.")

    try:
        import pikepdf  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "La ressource PDF a été trouvée, mais sa validation demande "
            "pikepdf : python -m pip install pikepdf"
        ) from exc
    try:
        diagnostics = inspect_detached_page_trees(data)
        page_count = diagnostics["visible_page_count"]
    except Exception as exc:
        raise RuntimeError(
            "La ressource PDF détectée ne peut pas être validée : " f"{exc}"
        ) from exc
    if page_count < 1:
        raise RuntimeError("La ressource PDF détectée ne contient aucune page.")
    return data, page_count, diagnostics
