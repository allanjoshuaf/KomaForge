"""Dedicated adapter for Scribd's layered document reader."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import unquote, urlparse

from ..models import (
    Confidence,
    Coverage,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
)
from ..paths import canonical_source_identity, clean_publication_title
from .catalog import SourceAccess, SourceMetadata, SourceStatus
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceReference,
    SourceSession,
)


_DOCUMENT_PATH = re.compile(r"^/document/(?P<document_id>[0-9]+)(?:/|$)")
_PAGE_ID = re.compile(r"^outer_page_(?P<number>[0-9]+)$")
_TITLE_SUFFIX = re.compile(
    r"\s*(?:[-|]\s*)?(?:scribd|pdf)\s*$",
    re.IGNORECASE,
)
def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _document_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host != "scribd.com" and not host.endswith(".scribd.com"):
        return None
    match = _DOCUMENT_PATH.match(parsed.path)
    return match.group("document_id") if match else None


def _page_numbers(page) -> tuple[int, ...]:
    values = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('[id^="outer_page_"]'))
          .map(node => Number(node.id.slice('outer_page_'.length)))
          .filter(value => Number.isInteger(value) && value > 0)
        """
    )
    return tuple(sorted({int(value) for value in values or () if int(value) > 0}))


def _hide_external_overlays(page) -> int:
    """Hide site chrome that could otherwise cover a rendered document page."""

    return int(
        page.evaluate(
            """
            () => {
              const pages = Array.from(
                document.querySelectorAll('[id^="outer_page_"]')
              );
              let hidden = 0;
              for (const node of document.querySelectorAll('body *')) {
                if (
                  pages.some(page =>
                    page === node || page.contains(node) || node.contains(page)
                  )
                ) {
                  continue;
                }
                const style = getComputedStyle(node);
                if (style.position !== 'fixed' && style.position !== 'sticky') {
                  continue;
                }
                const text = (node.innerText || '').toLocaleLowerCase();
                if (
                  text.includes('unlock this document') ||
                  text.includes('unlock the next') ||
                  text.includes('subscribe to read') ||
                  text.includes('start your 30 day free trial')
                ) {
                  continue;
                }
                node.setAttribute('data-komaforge-scribd-overlay', 'hidden');
                node.style.setProperty('visibility', 'hidden', 'important');
                hidden += 1;
              }
              return hidden;
            }
            """
        )
        or 0
    )


def _access_gate_state(page) -> dict[str, object]:
    try:
        state = page.evaluate(
            """
            () => { // scribd_access_gate
              const blurred = Array.from(
                document.querySelectorAll('.outer_page.blurred_page')
              ).map(node => node.id || 'unknown');
              const markers = [
                'unlock this document',
                'unlock the next',
                'subscribe to read',
                'start your 30 day free trial'
              ];
              const visibleText = (document.body?.innerText || '').toLocaleLowerCase();
              const messages = markers.filter(marker =>
                visibleText.includes(marker)
              );
              return {
                active: blurred.length > 0 && messages.length > 0,
                blurred,
                messages
              };
            }
            """
        )
    except Exception:
        return {"active": False, "blurred": (), "messages": ()}
    if not isinstance(state, dict):
        return {"active": False, "blurred": (), "messages": ()}
    return {
        "active": bool(state.get("active")),
        "blurred": tuple(str(value) for value in state.get("blurred") or ()),
        "messages": tuple(str(value) for value in state.get("messages") or ()),
    }


def _wait_for_access_gate(
    page,
    *,
    access_gate_prompt=None,
) -> bool:
    state = _access_gate_state(page)
    if not state["active"]:
        return False
    try:
        page.wait_for_function(
            """
            () => document.querySelectorAll('.outer_page.blurred_page').length === 0
            """,
            timeout=12_000,
        )
    except Exception:
        pass
    state = _access_gate_state(page)
    if not state["active"]:
        return True
    if callable(access_gate_prompt):
        access_gate_prompt(
            "Scribd demande de regarder une publicité pour libérer les pages. "
            "Terminez cette étape dans Chrome, puis appuyez sur Entrée ici..."
        )
        state = _access_gate_state(page)
        if not state["active"]:
            return True
    blurred = ", ".join(state["blurred"]) or "page inconnue"
    raise RuntimeError(
        "Scribd limite temporairement l'accès "
        f"({blurred}). La publicité de déverrouillage ne s'est pas chargée ou "
        "n'a pas été terminée. KomaForge refuse d'archiver le panneau flouté "
        "comme une page réussie. Relancez avec --wait-for-user, puis terminez "
        "le déverrouillage officiel dans Chrome; un bloqueur de publicités ou "
        "un VPN filtrant peut empêcher ce parcours."
    )


def _capture_page_png(page, locator, cdp_session) -> bytes:
    if cdp_session is None:
        return locator.screenshot(type="png", scale="css", timeout=30_000)
    bounds = locator.evaluate(
        """
        node => {
          const rect = node.getBoundingClientRect();
          return {
            x: rect.left + scrollX,
            y: rect.top + scrollY,
            width: rect.width,
            height: rect.height
          };
        }
        """
    )
    capture = cdp_session.send(
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {
                "x": max(0, float(bounds["x"])),
                "y": max(0, float(bounds["y"])),
                "width": float(bounds["width"]),
                "height": float(bounds["height"]),
                "scale": 1,
            },
        },
    )
    return base64.b64decode(capture["data"], validate=True)


def _publication_title(page, source_url: str) -> str:
    title = ""
    try:
        title = str(
            page.locator('meta[property="og:title"]').first.get_attribute("content")
            or ""
        )
    except Exception:
        pass
    if not title:
        title = str(page.title() or "")
    title = _TITLE_SUFFIX.sub("", clean_publication_title(title)).strip(" ._-|")
    if title:
        return title
    slug = unquote(urlparse(source_url).path.rstrip("/").split("/")[-1])
    return clean_publication_title(slug.replace("-", " ")) or "Scribd document"


def _render_resources(
    page,
    *,
    canonical: str,
    expected: int | None,
    progress=None,
    access_gate_prompt=None,
) -> ResourceSet:
    page_numbers = _page_numbers(page)
    if not page_numbers:
        raise RuntimeError(
            "Scribd a reconnu le document, mais aucune page outer_page_N "
            "n'est disponible dans le lecteur."
        )
    expected_total = max(expected or 0, max(page_numbers))
    try:
        page.evaluate(
            "() => document.fonts ? document.fonts.ready.then(() => true) : true"
        )
    except Exception:
        pass
    _wait_for_access_gate(page, access_gate_prompt=access_gate_prompt)
    _hide_external_overlays(page)

    cdp_session = None
    try:
        cdp_session = page.context.new_cdp_session(page)
    except Exception:
        pass

    resources: list[Resource] = []
    try:
        for position, page_number in enumerate(page_numbers, start=1):
            locator = page.locator(f"#outer_page_{page_number}").first
            locator.scroll_into_view_if_needed(timeout=30_000)
            try:
                page.wait_for_timeout(150)
            except Exception:
                pass
            _wait_for_access_gate(page, access_gate_prompt=access_gate_prompt)
            _hide_external_overlays(page)
            try:
                text_length = len((locator.inner_text(timeout=5_000) or "").strip())
            except Exception:
                text_length = 0
            data = _capture_page_png(page, locator, cdp_session)
            gate_changed_during_capture = _wait_for_access_gate(
                page,
                access_gate_prompt=access_gate_prompt,
            )
            if gate_changed_during_capture:
                _hide_external_overlays(page)
                data = _capture_page_png(page, locator, cdp_session)
                if _wait_for_access_gate(
                    page,
                    access_gate_prompt=access_gate_prompt,
                ):
                    raise RuntimeError(
                        "L'état d'accès Scribd a changé deux fois pendant la "
                        f"capture de la page {page_number}; relancez l'extraction."
                    )
            if not isinstance(data, bytes) or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(
                    "Scribd n'a pas produit une image PNG valide pour "
                    f"la page {page_number}."
                )
            resources.append(
                Resource(
                    id=_stable_id("resource", f"{canonical}:{page_number}"),
                    kind=ResourceKind.IMAGE,
                    locator=(
                        "browser-blob://scribd/"
                        f"rendered-page-{page_number:04d}.png"
                    ),
                    position=page_number,
                    media_type="image/png",
                    filename=f"page-{page_number:04d}.png",
                    metadata={
                        "_embedded_data": data,
                        "_embedded_content_type": "image/png",
                        "document_index": page_number,
                        "rendered_text_characters": text_length,
                        "source": "adaptateur Scribd : page DOM rendue complète",
                    },
                )
            )
            try:
                locator.evaluate(
                    """
                    node => {
                      const rect = node.getBoundingClientRect();
                      node.style.setProperty(
                        'height', `${rect.height}px`, 'important'
                      );
                      node.style.setProperty(
                        'min-height', `${rect.height}px`, 'important'
                      );
                      node.style.setProperty(
                        'background', '#fff', 'important'
                      );
                      node.replaceChildren();
                    }
                    """
                )
            except Exception:
                pass
            if callable(progress):
                progress(position, len(page_numbers))
    finally:
        if cdp_session is not None:
            try:
                cdp_session.detach()
            except Exception:
                pass

    coverage = Coverage.from_counts(
        len(resources),
        expected_total,
        unit="resources",
        evidence="conteneurs Scribd outer_page_N consécutifs",
        confidence=Confidence.HIGH,
        detail="texte et illustrations capturés ensemble depuis le rendu du lecteur",
    )
    return ResourceSet(tuple(resources), coverage)


class ScribdSource:
    id = "scribd"
    name = "Scribd"
    metadata = SourceMetadata(
        languages=("mul",),
        domains=("scribd.com", "www.scribd.com", "fr.scribd.com", "ru.scribd.com"),
        version="1",
        status=SourceStatus.VALIDATED,
        status_reason=(
            "231/231 layered pages were rendered with their DOM text; persistent "
            "advertisement access gates are detected and never archived as pages"
        ),
        access=SourceAccess.VARIABLE,
        family_ids=("paginated-images",),
        last_verified="2026-09-30",
    )

    def match(self, url: str, context: MatchContext) -> MatchResult:
        del context
        if _document_id(url) is None:
            return MatchResult.no_match("not a Scribd /document/<id>/ URL")
        return MatchResult.recognized(
            "official Scribd document URL",
            confidence=Confidence.HIGH,
        )

    def get_publication(
        self,
        reference: SourceReference,
        session: SourceSession,
    ) -> Publication:
        if reference.source_id != self.id:
            raise ValueError(
                f"reference belongs to {reference.source_id!r}, not {self.id!r}"
            )
        if session.page is None:
            raise RuntimeError("ScribdSource requires a prepared browser page")
        source_url = reference.url or reference.value
        canonical = canonical_source_identity(source_url)
        page_numbers = _page_numbers(session.page)
        expected = max(page_numbers) if page_numbers else None
        coverage = Coverage.from_counts(
            0,
            None,
            unit="resources",
            evidence="lecteur Scribd avant rendu",
            confidence=Confidence.MEDIUM,
        )
        title = _publication_title(session.page, source_url)
        part = Part(
            id=_stable_id("part", canonical),
            kind=PartKind.DOCUMENT,
            title=title,
            position=1,
            number="1",
            source_url=source_url,
            coverage=coverage,
            metadata={"expected_rendered_pages": expected},
        )
        return Publication(
            id=_stable_id("publication", canonical),
            work_id=_stable_id("work", canonical),
            source_id=self.id,
            title=title,
            source_url=source_url,
            parts=(part,),
            coverage=coverage,
            metadata={
                "publication_type": "document",
                "document_id": _document_id(source_url),
                "rendering": "layered-dom-page",
            },
        )

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
        del session
        if publication.source_id != self.id:
            raise ValueError(
                f"publication belongs to {publication.source_id!r}, not {self.id!r}"
            )
        return publication.parts

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        if session.page is None:
            raise RuntimeError("ScribdSource requires a prepared browser page")
        expected_value = part.metadata.get("expected_rendered_pages")
        expected = int(expected_value) if expected_value else None
        return _render_resources(
            session.page,
            canonical=canonical_source_identity(part.source_url),
            expected=expected,
            progress=session.options.get("resource_progress"),
            access_gate_prompt=session.options.get("access_gate_prompt"),
        )
