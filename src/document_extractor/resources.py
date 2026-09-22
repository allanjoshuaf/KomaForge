from __future__ import annotations

import base64
import gzip
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes, urlparse


@dataclass(frozen=True)
class ResourceInfo:
    kind: str
    extension: str
    media_type: str
    data: bytes
    source_sha256: str
    sha256: str
    normalized: bool = False
    normalization: str | None = None


def decode_data_uri(uri: str) -> tuple[bytes, str]:
    if not uri.lower().startswith("data:") or "," not in uri:
        raise ValueError("URI data: invalide")
    header, payload = uri.split(",", 1)
    metadata = header[5:].split(";")
    media_type = metadata[0] or "text/plain"
    if any(part.lower() == "base64" for part in metadata[1:]):
        try:
            return base64.b64decode(payload, validate=True), media_type
        except ValueError as exc:
            raise ValueError("Base64 invalide dans l'URI data:") from exc
    return unquote_to_bytes(payload), media_type


def _looks_like_svg(data: bytes) -> bool:
    prefix = data[:8192].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if prefix.startswith(b"<?xml"):
        return b"<svg" in prefix
    return prefix.startswith(b"<svg") or b"<svg" in prefix[:1024]


def _looks_like_html(data: bytes) -> bool:
    prefix = data[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    return prefix.startswith((b"<!doctype html", b"<html"))


def _make_info(
    kind: str,
    extension: str,
    media_type: str,
    source: bytes,
    data: bytes | None = None,
    normalization: str | None = None,
) -> ResourceInfo:
    final = source if data is None else data
    return ResourceInfo(
        kind=kind,
        extension=extension,
        media_type=media_type,
        data=final,
        source_sha256=hashlib.sha256(source).hexdigest(),
        sha256=hashlib.sha256(final).hexdigest(),
        normalized=final != source or normalization is not None,
        normalization=normalization,
    )


def detect_resource(
    data: bytes,
    content_type: str = "",
    url: str = "",
    max_uncompressed_bytes: int = 100 * 1024 * 1024,
) -> ResourceInfo:
    """Identifie une ressource par son contenu, l'extension restant un simple indice."""
    if not data:
        raise ValueError("Ressource vide")
    source = data
    lowered_type = content_type.lower().split(";", 1)[0].strip()
    suffix = (urlparse(url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url).path else "")

    if data.startswith(b"\x1f\x8b"):
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise ValueError("Flux GZIP/SVGZ invalide") from exc
        if len(data) > max_uncompressed_bytes:
            raise ValueError("Ressource décompressée trop volumineuse")
        inner = detect_resource(data, "", url.removesuffix("z"), max_uncompressed_bytes)
        return _make_info(
            inner.kind,
            inner.extension,
            inner.media_type,
            source,
            inner.data,
            f"gzip vers {inner.kind}",
        )

    if data.startswith(b"\xff\xd8\xff"):
        return _make_info("jpeg", ".jpg", "image/jpeg", source)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _make_info("png", ".png", "image/png", source)
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _make_info("webp", ".webp", "image/webp", source)
    if data.startswith((b"GIF87a", b"GIF89a")):
        return _make_info("gif", ".gif", "image/gif", source)
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        return _make_info("avif", ".avif", "image/avif", source)
    if data.startswith(b"%PDF-"):
        return _make_info("pdf", ".pdf", "application/pdf", source)
    if data.startswith(b"PK\x03\x04"):
        return _make_info("zip", ".zip", "application/zip", source)
    if data.startswith(b"Rar!\x1a\x07"):
        return _make_info("rar", ".rar", "application/vnd.rar", source)
    if _looks_like_svg(data):
        note = "extension .svgz contenant un SVG non compressé" if suffix == "svgz" else None
        return _make_info("svg", ".svg", "image/svg+xml", source, normalization=note)
    if _looks_like_html(data):
        return _make_info("html", ".html", "text/html", source)

    mime_fallbacks = {
        "image/jpeg": ("jpeg", ".jpg"),
        "image/png": ("png", ".png"),
        "image/webp": ("webp", ".webp"),
        "image/gif": ("gif", ".gif"),
        "image/avif": ("avif", ".avif"),
    }
    if lowered_type in mime_fallbacks:
        kind, extension = mime_fallbacks[lowered_type]
        return _make_info(kind, extension, lowered_type, source)
    raise ValueError(
        f"Type de ressource inconnu ({lowered_type or suffix or 'aucun indice'})"
    )


def resource_from_url_value(value: str) -> tuple[bytes, str] | None:
    if value.lower().startswith("data:"):
        return decode_data_uri(value)
    return None


def is_page_resource(info: ResourceInfo) -> bool:
    return info.kind in {"jpeg", "png", "webp", "gif", "avif", "svg"}
