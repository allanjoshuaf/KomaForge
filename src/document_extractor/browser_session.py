"""Chrome session lifecycle and bounded source navigation."""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


PAGE_TIMEOUT_MS = 90_000


def cleanup_temporary_profile(
    temporary_profile: tempfile.TemporaryDirectory,
    profile_dir: Path,
    attempts: int = 8,
) -> bool:
    """Supprime un profil Chrome temporaire malgré les verrous Windows brefs."""

    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            temporary_profile.cleanup()
            return not profile_dir.exists()
        except OSError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    try:
        shutil.rmtree(profile_dir)
        return True
    except OSError as exc:
        last_error = exc
    print(
        "[TEMP] Profil Chrome non supprimé après fermeture : "
        f"{profile_dir} ({last_error})"
    )
    return False


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_chrome(port: int, timeout_seconds: int = 60) -> dict:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(
        "Chrome n'a pas ouvert son interface de contrôle. "
        "Un autre Chrome utilise peut-être le même profil."
    ) from last_error


def _replace_failed_page(context, page):
    replacement = context.new_page()
    try:
        page.close()
    except Exception:
        pass
    return replacement


def _http_origin_warmup_url(url: str) -> str | None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"http://{parsed.hostname}/"


def navigate_to_source(context, page, url: str, retries: int = 3):
    """Open the source and recover from a Chromium SSL false start.

    Some filtered Windows networks return ERR_SSL_PROTOCOL_ERROR for the first
    direct Chromium request while accepting the site's HTTP -> HTTPS redirect.
    The recovery request contains only the origin, never the document path or
    query, and it must land on HTTPS on the same host before the source URL is
    tried again.
    """

    attempts = max(1, retries)
    target = urlparse(url)
    warmup_url = _http_origin_warmup_url(url)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            return page
        except Exception as exc:
            last_error = exc
            print(f"[NAVIGATION {attempt}/{attempts}] {str(exc).splitlines()[0]}")

            if "ERR_SSL_PROTOCOL_ERROR" in str(exc) and warmup_url:
                page = _replace_failed_page(context, page)
                try:
                    print("Récupération SSL : initialisation sécurisée du domaine...")
                    page.goto(
                        warmup_url,
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT_MS,
                    )
                    landed = urlparse(page.url)
                    if landed.scheme != "https" or landed.hostname != target.hostname:
                        raise RuntimeError(
                            "le domaine n'a pas redirigé vers le même hôte en HTTPS"
                        )
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT_MS,
                    )
                    print("Récupération SSL réussie.")
                    return page
                except Exception as recovery_error:
                    last_error = recovery_error
                    print(
                        "Récupération SSL échouée : "
                        f"{str(recovery_error).splitlines()[0]}"
                    )

            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
                page = _replace_failed_page(context, page)

    raise RuntimeError(
        f"Impossible d'ouvrir le document après {attempts} tentative(s)."
    ) from last_error
