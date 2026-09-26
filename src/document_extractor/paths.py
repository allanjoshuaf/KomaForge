from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse


GENERIC_TITLES = {
    "document",
    "reader",
    "mangareader",
    "ebooks.com reader",
    "loading",
    "preview",
}

CHAPTER_PATTERN = re.compile(
    r"\b(?:chapter|chapitre|ch(?:apter)?[._ -]?|c)\s*([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)

TITLE_SUFFIXES = (
    r"\s*[-|]\s*ebooks\.com reader(?:\s*\(preview\))?\s*$",
    r"\s*[-|]\s*mangareader\s*$",
    r"\s*[-|]\s*manga\s*up!?\s*$",
    r"\s*[-|]\s*calam[eé]o\s*$",
    r"\s*\(preview\)\s*$",
)


def safe_slug(value: str) -> str:
    """Retourne un nom de dossier portable, sans nom d'utilisateur codé en dur."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")
    value = re.sub(r"-{2,}", "-", value)
    value = value[:96] or "document"
    if value.casefold() in {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }:
        value = f"{value}-document"
    return value


def application_home() -> Path:
    """Dossier du lanceur portable, ou dossier courant après installation CLI."""
    configured = os.environ.get("DOCUMENT_EXTRACTOR_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "extract.py").is_file():
            return parent
    return Path.cwd().resolve()


def default_output_root(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return (base_dir / "extractions").resolve()
    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
        return Path(f"{system_drive}\\Extractions\\Manga").resolve()
    return (application_home() / "extractions" / "manga").resolve()


def default_profile_dir() -> Path:
    """Profil Chrome KomaForge persistant, indépendant du nom de l'utilisateur."""
    configured = os.environ.get("KOMAFORGE_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local_data = os.environ.get("LOCALAPPDATA")
        if local_data:
            return (Path(local_data) / "KomaForge" / "ChromeProfile").resolve()
    return (Path.home() / ".komaforge" / "chrome-profile").resolve()


def default_output_dir(url: str, base_dir: Path | None = None) -> Path:
    parsed = urlparse(url)
    host = parsed.hostname or "document"
    path_name = Path(parsed.path.rstrip("/")).name or "document"
    document_name = safe_slug(f"{host}-{path_name}")
    root = default_output_root(base_dir)
    return (root / document_name).resolve()


def clean_publication_title(value: str) -> str:
    title = " ".join((value or "").split()).strip(" ._-|")
    changed = True
    while title and changed:
        changed = False
        for pattern in TITLE_SUFFIXES:
            cleaned = re.sub(pattern, "", title, flags=re.IGNORECASE).strip(" ._-|")
            if cleaned != title:
                title = cleaned
                changed = True
    return title


def publication_folder_title(
    page_title: str,
    source_url: str,
    *,
    publication_is_work: bool = False,
) -> str:
    """Construit un titre humain même lorsque l'URL du lecteur est opaque."""
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    query_title = clean_publication_title(
        unquote(query.get("title", [""])[0]).strip()
    )
    detected_title = clean_publication_title(page_title)
    title = query_title or detected_title

    if not title or title.casefold() in GENERIC_TITLES:
        path_name = Path(parsed.path.rstrip("/")).name
        title = (
            clean_publication_title(unquote(path_name))
            or parsed.hostname
            or "document"
        )

    if query_title and not publication_is_work:
        chapter_match = CHAPTER_PATTERN.search(page_title or "")
        if not chapter_match:
            nested_url = unquote(query.get("url", [""])[0])
            chapter_match = CHAPTER_PATTERN.search(nested_url)
        if chapter_match and not CHAPTER_PATTERN.search(query_title):
            title = f"{query_title} - Chapter {chapter_match.group(1)}"
    return title


def canonical_source_identity(source_url: str) -> str:
    """Stabilise l'identité d'une source malgré les jetons de session volatils."""
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    nested = query.get("url", [""])[0]
    if nested:
        return canonical_source_identity(unquote(nested))

    if query.get("bid"):
        stable_query = urlencode({"bid": query["bid"][0]})
    else:
        volatile = {"hash", "reqid", "session", "t", "token", "uid"}
        stable_items = sorted(
            (key, value)
            for key, values in query.items()
            if key.casefold() not in volatile
            for value in values
        )
        stable_query = urlencode(stable_items)
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/"),
            "",
            stable_query,
            "",
        )
    )


def _existing_source_urls(output_dir: Path) -> list[str]:
    sources: list[str] = []
    for name in ("pages.json", "publication.json"):
        manifest = output_dir / name
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source = data.get("source_url")
        if isinstance(source, str) and source:
            sources.append(source)
    return sources


def output_dir_matches_source(output_dir: Path, source_url: str) -> bool:
    expected = canonical_source_identity(source_url)
    return any(
        canonical_source_identity(existing) == expected
        for existing in _existing_source_urls(output_dir)
    )


def choose_title_output_dir(
    root: Path,
    title: str,
    source_url: str,
    expected_manifest: str | None = None,
) -> Path:
    """Réutilise uniquement une sortie compatible, sinon ajoute un suffixe."""
    def reusable(candidate: Path) -> bool:
        if not output_dir_matches_source(candidate, source_url):
            return False
        return expected_manifest is None or (candidate / expected_manifest).is_file()

    base = (root / safe_slug(title)).resolve()
    if not base.exists() or reusable(base):
        return base
    for index in range(2, 10_000):
        candidate = base.with_name(f"{base.name}-{index}")
        if not candidate.exists() or reusable(candidate):
            return candidate
    raise RuntimeError("Impossible de trouver un dossier de sortie libre.")


def ensure_output_dir_is_compatible(output_dir: Path, source_url: str) -> None:
    """Empêche une sortie explicitement choisie d'écraser un autre ouvrage."""
    if not output_dir.exists():
        return
    sources = _existing_source_urls(output_dir)
    if sources and output_dir_matches_source(output_dir, source_url):
        return
    if sources or any(output_dir.iterdir()):
        raise RuntimeError(
            "Le dossier de sortie contient déjà un autre ouvrage. "
            "Choisissez un dossier différent pour éviter tout écrasement."
        )
