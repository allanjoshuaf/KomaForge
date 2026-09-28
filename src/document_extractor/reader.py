"""Local, browser-based reader for validated CBZ and image-folder artifacts."""

from __future__ import annotations

import html
import json
import mimetypes
import re
import secrets
import threading
import webbrowser
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


IMAGE_SUFFIXES = frozenset(
    {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
)
MAX_PAGE_BYTES = 100 * 1024 * 1024
MAX_PROGRESS_BODY_BYTES = 4096

ProgressCallback = Callable[[int, bool], None]
BrowserOpener = Callable[[str], object]


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(chunk)) if chunk.isdigit() else (1, chunk.casefold())
        for chunk in re.split(r"(\d+)", value)
    )


def _media_type(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name)
    if guessed and guessed.startswith("image/"):
        return guessed
    suffix = Path(name).suffix.casefold()
    return {
        ".avif": "image/avif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def _safe_archive_member(name: str) -> bool:
    value = name.replace("\\", "/")
    path = PurePosixPath(value)
    return (
        bool(value)
        and not value.startswith("/")
        and not path.is_absolute()
        and ".." not in path.parts
        and Path(path.name).suffix.casefold() in IMAGE_SUFFIXES
    )


@dataclass(frozen=True, slots=True)
class ReaderPage:
    name: str
    media_type: str
    size: int


class ReaderDocument:
    """A bounded view of the image pages contained in one local artifact."""

    def __init__(self, path: Path, pages: tuple[ReaderPage, ...], kind: str) -> None:
        self.path = path.expanduser().resolve()
        self.pages = pages
        self.kind = kind

    @classmethod
    def from_path(cls, path: Path) -> ReaderDocument:
        resolved = path.expanduser().resolve()
        if resolved.is_dir():
            files: list[Path] = []
            for candidate in resolved.rglob("*"):
                if not candidate.is_file():
                    continue
                candidate = candidate.resolve()
                if not candidate.is_relative_to(resolved):
                    continue
                if candidate.suffix.casefold() in IMAGE_SUFFIXES:
                    files.append(candidate)
            files.sort(key=lambda item: _natural_key(item.relative_to(resolved).as_posix()))
            pages = tuple(
                ReaderPage(
                    item.relative_to(resolved).as_posix(),
                    _media_type(item.name),
                    item.stat().st_size,
                )
                for item in files
            )
            kind = "directory"
        elif resolved.is_file() and resolved.suffix.casefold() in {".cbz", ".zip"}:
            try:
                with zipfile.ZipFile(resolved) as archive:
                    entries = [
                        entry
                        for entry in archive.infolist()
                        if not entry.is_dir() and _safe_archive_member(entry.filename)
                    ]
            except zipfile.BadZipFile as exc:
                raise ValueError("the CBZ artifact is not a valid ZIP archive") from exc
            entries.sort(key=lambda item: _natural_key(item.filename.replace("\\", "/")))
            pages = tuple(
                ReaderPage(
                    entry.filename,
                    _media_type(entry.filename),
                    entry.file_size,
                )
                for entry in entries
            )
            kind = "archive"
        else:
            raise ValueError(
                "the internal reader supports CBZ archives and image folders; "
                "use 'library open' for this format"
            )
        if not pages:
            raise ValueError("the artifact contains no readable image page")
        oversized = next((page for page in pages if page.size > MAX_PAGE_BYTES), None)
        if oversized is not None:
            raise ValueError(
                f"reader page exceeds the {MAX_PAGE_BYTES // (1024 * 1024)} MB limit: "
                f"{oversized.name}"
            )
        return cls(resolved, pages, kind)

    def read_page(self, index: int) -> bytes:
        if index < 1 or index > len(self.pages):
            raise IndexError(index)
        page = self.pages[index - 1]
        if self.kind == "directory":
            candidate = (self.path / Path(page.name)).resolve()
            if not candidate.is_relative_to(self.path) or not candidate.is_file():
                raise FileNotFoundError(page.name)
            data = candidate.read_bytes()
        else:
            with zipfile.ZipFile(self.path) as archive:
                info = archive.getinfo(page.name)
                if info.file_size > MAX_PAGE_BYTES:
                    raise ValueError("reader page exceeds the size limit")
                data = archive.read(info)
        if len(data) > MAX_PAGE_BYTES:
            raise ValueError("reader page exceeds the size limit")
        return data


def build_reader_html(
    *,
    title: str,
    token: str,
    page_count: int,
    start_position: int,
) -> bytes:
    safe_title = html.escape(title, quote=True)
    title_json = json.dumps(title, ensure_ascii=False).replace("<", "\\u003c")
    pages = "\n".join(
        f'''<figure class="page" id="page-{position}" data-position="{position}">
          <img src="/{token}/page/{position}" loading="lazy" decoding="async"
               alt="Page {position} sur {page_count}" />
          <figcaption>Page {position}</figcaption>
        </figure>'''
        for position in range(1, page_count + 1)
    )
    markup = f'''<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <title>{safe_title} · KomaForge</title>
  <style>
    :root {{
      --background: #0d0d0f;
      --surface: #17171a;
      --surface-raised: #202024;
      --foreground: #f4f1eb;
      --muted: #c6beb3;
      --border: #3c3937;
      --accent: #e38452;
      --on-accent: #21120b;
      --focus: #ffd3b8;
      --toolbar-height: 104px;
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; background: var(--background); }}
    body {{
      margin: 0;
      min-width: 320px;
      background:
        radial-gradient(circle at 50% -10%, rgba(227, 132, 82, .09), transparent 32rem),
        var(--background);
      color: var(--foreground);
    }}
    button {{ font: inherit; }}
    .skip-link {{
      position: fixed;
      z-index: 100;
      top: 8px;
      left: 8px;
      padding: 10px 14px;
      background: var(--foreground);
      color: var(--background);
      transform: translateY(-160%);
    }}
    .skip-link:focus {{ transform: translateY(0); }}
    .toolbar {{
      position: sticky;
      z-index: 20;
      top: 0;
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(180px, 320px) auto;
      gap: 16px;
      align-items: center;
      min-height: var(--toolbar-height);
      padding: 14px clamp(16px, 3vw, 40px);
      border-bottom: 1px solid var(--border);
      background: rgba(13, 13, 15, .94);
      backdrop-filter: blur(16px);
    }}
    .identity {{ min-width: 0; }}
    .eyebrow {{
      margin: 0 0 4px;
      color: var(--accent);
      font: 600 12px/1.2 ui-monospace, "Cascadia Code", monospace;
      letter-spacing: .12em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      overflow: hidden;
      color: var(--foreground);
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(18px, 2.1vw, 28px);
      font-weight: 500;
      line-height: 1.15;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .reading-status {{ display: grid; gap: 7px; min-width: 0; }}
    .position {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      color: var(--muted);
      font: 500 13px/1.4 ui-monospace, "Cascadia Code", monospace;
    }}
    progress {{
      width: 100%;
      height: 5px;
      overflow: hidden;
      border: 0;
      border-radius: 999px;
      background: var(--surface-raised);
    }}
    progress::-webkit-progress-bar {{ background: var(--surface-raised); }}
    progress::-webkit-progress-value {{ background: var(--accent); }}
    progress::-moz-progress-bar {{ background: var(--accent); }}
    .controls {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }}
    .control {{
      min-height: 44px;
      padding: 9px 13px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      color: var(--foreground);
      cursor: pointer;
      transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
      touch-action: manipulation;
    }}
    .control:hover {{ border-color: #69625d; background: var(--surface-raised); }}
    .control:active {{ background: #29282c; }}
    .control[aria-pressed="true"] {{
      border-color: var(--accent);
      background: var(--accent);
      color: var(--on-accent);
    }}
    .control:focus-visible, .page:focus-visible, .skip-link:focus-visible {{
      outline: 3px solid var(--focus);
      outline-offset: 3px;
    }}
    .reader {{
      display: grid;
      justify-items: center;
      gap: 24px;
      padding: 28px 16px 56px;
      outline: none;
    }}
    .page {{
      width: min(100%, 1120px);
      margin: 0;
      scroll-margin-top: calc(var(--toolbar-height) + 18px);
    }}
    .page img {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 160px;
      border: 1px solid #2b2929;
      background: #111114;
      box-shadow: 0 16px 48px rgba(0, 0, 0, .34);
    }}
    .page figcaption {{
      margin-top: 8px;
      color: var(--muted);
      font: 500 12px/1.4 ui-monospace, "Cascadia Code", monospace;
      text-align: center;
    }}
    body.original-size .page {{ width: max-content; max-width: none; }}
    body.original-size .page img {{ width: auto; max-width: none; }}
    .shortcuts {{
      position: fixed;
      right: 16px;
      bottom: 16px;
      z-index: 10;
      max-width: min(360px, calc(100vw - 32px));
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(23, 23, 26, .96);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      opacity: .78;
    }}
    .shortcuts kbd {{ color: var(--foreground); font-family: ui-monospace, monospace; }}
    @media (max-width: 900px) {{
      :root {{ --toolbar-height: 174px; }}
      .toolbar {{ grid-template-columns: 1fr; gap: 10px; }}
      .controls {{ justify-content: flex-start; }}
      .reading-status {{ max-width: none; }}
    }}
    @media (max-width: 520px) {{
      :root {{ --toolbar-height: 224px; }}
      .toolbar {{ padding: 12px 14px; }}
      .controls {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .control {{ padding-inline: 8px; }}
      .reader {{ gap: 16px; padding-inline: 8px; }}
      .shortcuts {{ display: none; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      html {{ scroll-behavior: auto; }}
      *, *::before, *::after {{ transition-duration: .01ms !important; }}
    }}
  </style>
</head>
<body>
  <a class="skip-link" href="#reader">Aller aux pages</a>
  <header class="toolbar">
    <div class="identity">
      <p class="eyebrow">KomaForge · Lecteur local</p>
      <h1 title="{safe_title}">{safe_title}</h1>
    </div>
    <div class="reading-status" role="status" aria-live="polite">
      <div class="position"><span id="position">Page {start_position} / {page_count}</span><span id="percent">0 %</span></div>
      <progress id="progress" max="{page_count}" value="{start_position}">Page {start_position} sur {page_count}</progress>
    </div>
    <nav class="controls" aria-label="Commandes de lecture">
      <button class="control" id="previous" type="button">Précédente</button>
      <button class="control" id="next" type="button">Suivante</button>
      <button class="control" id="fit" type="button" aria-pressed="true">Ajuster</button>
      <button class="control" id="close" type="button">Fermer</button>
    </nav>
  </header>
  <main class="reader" id="reader" tabindex="-1" aria-label="Pages de {safe_title}">
    {pages}
  </main>
  <aside class="shortcuts" aria-label="Raccourcis clavier">
    <kbd>←</kbd>/<kbd>→</kbd> page · <kbd>Début</kbd>/<kbd>Fin</kbd> extrémités ·
    <kbd>F</kbd> ajuster · <kbd>Q</kbd> fermer
  </aside>
  <script>
    (() => {{
      const title = {title_json};
      const total = {page_count};
      const base = "/{token}";
      const initialPosition = {start_position};
      let current = initialPosition;
      let saveTimer = 0;
      let closing = false;
      let viewportTracking = false;
      const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const pages = [...document.querySelectorAll(".page")];
      const position = document.getElementById("position");
      const percent = document.getElementById("percent");
      const progress = document.getElementById("progress");
      const fit = document.getElementById("fit");
      const toolbar = document.querySelector(".toolbar");
      let viewportFrame = 0;

      function updateStatus(next) {{
        if (closing) return;
        current = Math.min(total, Math.max(1, next));
        const value = Math.round((current / total) * 100);
        position.textContent = `Page ${{current}} / ${{total}}`;
        percent.textContent = `${{value}} %`;
        progress.value = current;
        progress.textContent = `Page ${{current}} sur ${{total}}`;
        document.title = `${{current}}/${{total}} · ${{title}} · KomaForge`;
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => {{
          fetch(`${{base}}/progress`, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{position: current, completed: current === total}}),
            keepalive: true,
          }}).catch(() => {{}});
        }}, 280);
      }}

      function goTo(next) {{
        const target = Math.min(total, Math.max(1, next));
        pages[target - 1].scrollIntoView({{behavior: reduceMotion ? "auto" : "smooth", block: "start"}});
        updateStatus(target);
      }}

      function syncFromViewport() {{
        viewportFrame = 0;
        if (closing || !viewportTracking) return;
        const toolbarBottom = toolbar.getBoundingClientRect().bottom;
        const marker = toolbarBottom + Math.max(1, (innerHeight - toolbarBottom) * .28);
        let nearest = pages[0];
        let distance = Infinity;
        for (const page of pages) {{
          const rect = page.getBoundingClientRect();
          if (rect.top <= marker && rect.bottom >= marker) {{ nearest = page; break; }}
          const nextDistance = Math.min(Math.abs(rect.top - marker), Math.abs(rect.bottom - marker));
          if (nextDistance < distance) {{ distance = nextDistance; nearest = page; }}
        }}
        updateStatus(Number(nearest.dataset.position));
      }}

      function scheduleViewportSync() {{
        if (!viewportFrame) viewportFrame = requestAnimationFrame(syncFromViewport);
      }}
      addEventListener("scroll", scheduleViewportSync, {{passive: true}});
      addEventListener("resize", scheduleViewportSync);

      document.getElementById("previous").addEventListener("click", () => goTo(current - 1));
      document.getElementById("next").addEventListener("click", () => goTo(current + 1));
      fit.addEventListener("click", () => {{
        const keepPosition = current;
        const original = document.body.classList.toggle("original-size");
        fit.setAttribute("aria-pressed", String(!original));
        fit.textContent = original ? "Largeur" : "Ajuster";
        requestAnimationFrame(() => goTo(keepPosition));
      }});
      document.getElementById("close").addEventListener("click", async () => {{
        if (closing) return;
        closing = true;
        clearTimeout(saveTimer);
        try {{
          await fetch(`${{base}}/progress`, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{position: current, completed: current === total}}),
            keepalive: true,
          }});
        }} catch (_error) {{}}
        try {{
          await fetch(`${{base}}/close`, {{method: "POST", keepalive: true}});
        }} catch (_error) {{}}
        document.body.innerHTML = '<main class="reader"><p>Lecteur fermé. Vous pouvez fermer cet onglet.</p></main>';
      }});
      document.addEventListener("keydown", (event) => {{
        if (["ArrowLeft", "ArrowUp", "PageUp"].includes(event.key)) {{ event.preventDefault(); goTo(current - 1); }}
        else if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(event.key)) {{ event.preventDefault(); goTo(current + 1); }}
        else if (event.key === "Home") {{ event.preventDefault(); goTo(1); }}
        else if (event.key === "End") {{ event.preventDefault(); goTo(total); }}
        else if (event.key.toLowerCase() === "f") {{ event.preventDefault(); fit.click(); }}
        else if (event.key.toLowerCase() === "q") {{ event.preventDefault(); document.getElementById("close").click(); }}
      }});
      addEventListener("load", async () => {{
        const target = pages[initialPosition - 1];
        const image = target.querySelector("img");
        try {{ await image.decode(); }} catch (_error) {{}}
        target.scrollIntoView({{behavior: "auto", block: "start"}});
        updateStatus(initialPosition);
        viewportTracking = true;
      }});
    }})();
  </script>
</body>
</html>'''
    return markup.encode("utf-8")


class _ReaderHttpServer(ThreadingHTTPServer):
    daemon_threads = True


class ReaderServer:
    """Loopback-only HTTP server for one reader session."""

    def __init__(
        self,
        document: ReaderDocument,
        *,
        title: str,
        start_position: int = 1,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.document = document
        self.title = title
        self.token = secrets.token_urlsafe(32)
        self.progress_callback = progress_callback
        self.start_position = min(len(document.pages), max(1, int(start_position)))
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *args: object) -> None:
                return

            def _headers(
                self,
                status: HTTPStatus,
                media_type: str,
                length: int,
                *,
                cache: str = "no-store",
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", media_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", cache)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data:; "
                    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                    "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
                )
                self.end_headers()

            def _send(self, status: HTTPStatus, media_type: str, data: bytes) -> None:
                self._headers(status, media_type, len(data))
                if self.command != "HEAD":
                    self.wfile.write(data)

            def _route(self) -> tuple[str, list[str]]:
                path = urlsplit(self.path).path
                prefix = f"/{owner.token}"
                if path != prefix and not path.startswith(f"{prefix}/"):
                    return "", []
                remainder = path[len(prefix) :].strip("/")
                return path, remainder.split("/") if remainder else []

            def do_HEAD(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                matched, parts = self._route()
                if not matched:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")
                    return
                if not parts:
                    body = build_reader_html(
                        title=owner.title,
                        token=owner.token,
                        page_count=len(owner.document.pages),
                        start_position=owner.start_position,
                    )
                    self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
                    return
                if len(parts) == 2 and parts[0] == "page" and parts[1].isdigit():
                    index = int(parts[1])
                    try:
                        page = owner.document.pages[index - 1]
                        data = owner.document.read_page(index)
                    except (IndexError, KeyError, OSError, ValueError):
                        self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")
                        return
                    self._headers(
                        HTTPStatus.OK,
                        page.media_type,
                        len(data),
                        cache="private, max-age=3600",
                    )
                    if self.command != "HEAD":
                        self.wfile.write(data)
                    return
                self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")

            def do_POST(self) -> None:
                matched, parts = self._route()
                if not matched:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")
                    return
                if parts == ["close"]:
                    self._send(HTTPStatus.NO_CONTENT, "text/plain", b"")
                    threading.Thread(target=owner.shutdown, daemon=True).start()
                    return
                if parts != ["progress"]:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length < 1 or length > MAX_PROGRESS_BODY_BYTES:
                    self._send(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"Invalid body")
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    position = payload["position"]
                    completed = payload["completed"]
                    if (
                        not isinstance(position, int)
                        or isinstance(position, bool)
                        or position < 1
                        or position > len(owner.document.pages)
                        or not isinstance(completed, bool)
                        or completed != (position == len(owner.document.pages))
                    ):
                        raise ValueError("invalid progress")
                    if owner.progress_callback is not None:
                        owner.progress_callback(position, completed)
                except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                    self._send(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"Invalid progress")
                    return
                self._send(HTTPStatus.NO_CONTENT, "text/plain", b"")

        self._server = _ReaderHttpServer(("127.0.0.1", 0), Handler)

    @property
    def url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/{self.token}/"

    def serve(
        self,
        *,
        open_browser: bool = True,
        browser_opener: BrowserOpener | None = None,
    ) -> None:
        try:
            if open_browser:
                (browser_opener or webbrowser.open)(self.url)
            self._server.serve_forever(poll_interval=0.2)
        finally:
            self._server.server_close()

    def shutdown(self) -> None:
        self._server.shutdown()


def serve_reader(
    document: ReaderDocument,
    *,
    title: str,
    start_position: int,
    progress_callback: ProgressCallback,
    browser_opener: BrowserOpener | None = None,
) -> None:
    server = ReaderServer(
        document,
        title=title,
        start_position=start_position,
        progress_callback=progress_callback,
    )
    print(f"Lecteur local : {server.url}")
    print("La progression est enregistrée automatiquement. Ctrl+C arrête le lecteur.")
    try:
        server.serve(browser_opener=browser_opener)
    except KeyboardInterrupt:
        print("Lecteur arrêté.")
