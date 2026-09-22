from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse


def safe_slug(value: str) -> str:
    """Retourne un nom de dossier portable, sans nom d'utilisateur codé en dur."""
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")
    return value[:96] or "document"


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


def default_output_dir(url: str, base_dir: Path | None = None) -> Path:
    parsed = urlparse(url)
    host = parsed.hostname or "document"
    path_name = Path(parsed.path.rstrip("/")).name or "document"
    document_name = safe_slug(f"{host}-{path_name}")
    if base_dir is not None:
        root = base_dir / "extractions"
    elif os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
        root = Path(f"{system_drive}\\Extractions\\Manga")
    else:
        root = application_home() / "extractions" / "manga"
    return (root / document_name).resolve()
