"""Normalized adapter for official eBooks.com product and reader sessions."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse

from ..detection import (
    _ebooks_reader_url,
    discover_linked_reader,
    is_ebooks_product_url,
)
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
from .catalog import SourceMetadata, SourceStatus
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceReference,
    SourceSession,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _is_reader_url(value: str) -> bool:
    return _ebooks_reader_url(value) is not None


def _stable_publication_url(
    reference_url: str,
    session: SourceSession,
) -> str:
    if is_ebooks_product_url(reference_url):
        return reference_url
    product_url = session.options.get("product_url")
    if isinstance(product_url, str) and is_ebooks_product_url(product_url):
        return product_url
    parsed = urlparse(reference_url)
    query = parse_qs(parsed.query)
    if _is_reader_url(reference_url) and query.get("bid"):
        return reference_url
    raise RuntimeError(
        "An eBooks reader session URL cannot be used as a stable publication "
        "identity; provide the official product URL"
    )


def _candidate_url(candidate: dict) -> str:
    explicit = candidate.get("url")
    if isinstance(explicit, str) and explicit:
        return explicit
    request = candidate.get("request")
    value = getattr(request, "url", "")
    if isinstance(value, str) and value:
        return value
    raise RuntimeError("document candidate has no request URL")


def _coverage_from_candidate(candidate: dict) -> Coverage:
    document_format = candidate.get("document_format")
    if document_format == "epub" and isinstance(candidate.get("epub_info"), dict):
        info = candidate["epub_info"]
        referenced = int(info.get("referenced_document_count") or 0)
        spine = int(info.get("spine_item_count") or 0)
        if referenced:
            available = len(info.get("present_referenced_documents") or [])
            return Coverage.from_counts(
                available,
                referenced,
                unit="sections",
                evidence="EPUB navigation document",
                confidence=Confidence.HIGH,
            )
        return Coverage.from_counts(
            spine,
            spine,
            unit="sections",
            evidence="EPUB spine",
            confidence=Confidence.HIGH,
        )
    if document_format == "pdf" and candidate.get("page_count") is not None:
        available = int(candidate["page_count"])
        expected_value = candidate.get("expected_page_count")
        expected = int(expected_value) if expected_value is not None else None
        return Coverage.from_counts(
            available,
            expected,
            unit="pages",
            evidence=str(candidate.get("expected_source") or "validated PDF"),
            confidence=Confidence.HIGH if expected is not None else Confidence.MEDIUM,
        )
    return Coverage.from_counts(
        1,
        None,
        unit="documents",
        evidence="browser network response",
        confidence=Confidence.MEDIUM,
    )


class EBooksSource:
    id = "ebooks"
    name = "eBooks.com"
    metadata = SourceMetadata(
        languages=("mul",),
        domains=("ebooks.com", "www.ebooks.com", "reader.ebooks.com"),
        version="1",
        status=SourceStatus.DEGRADED,
        status_reason="reader sessions may expose only a limited sample of the publication",
        family_ids=("direct-document",),
        last_verified="2026-09-27",
    )

    def match(self, url: str, context: MatchContext) -> MatchResult:
        if not is_ebooks_product_url(url) and not _is_reader_url(url):
            return MatchResult.no_match("not an official eBooks.com publication URL")
        return MatchResult.recognized(
            "official eBooks.com product or reader URL",
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
            raise RuntimeError("EBooksSource requires a prepared browser page")
        reference_url = reference.url or reference.value
        stable_url = _stable_publication_url(reference_url, session)
        reader_url = reference_url if _is_reader_url(reference_url) else None
        reader_action = None
        if reader_url is None:
            if session.browser_context is None:
                raise RuntimeError(
                    "EBooksSource requires a browser context to open a product preview"
                )
            reader_entry = discover_linked_reader(
                session.browser_context,
                session.page,
            )
            if reader_entry and reader_entry.get("error"):
                raise RuntimeError(
                    "eBooks product was recognized but its preview action failed: "
                    f"{reader_entry['error']}"
                )
            if not reader_entry or not reader_entry.get("url"):
                raise RuntimeError(
                    "eBooks product was recognized but exposed no Preview, "
                    "Read sample, or Read online session"
                )
            reader_url = str(reader_entry["url"])
            reader_action = reader_entry.get("action")

        canonical = canonical_source_identity(stable_url)
        title = clean_publication_title(
            str(session.options.get("title") or session.page.title() or "")
        )
        if not title:
            title = "eBooks publication"
        part = Part(
            id=_stable_id("part", canonical),
            kind=PartKind.DOCUMENT,
            title=title,
            position=1,
            source_url=reader_url,
            coverage=Coverage.from_counts(0, None, unit="resources"),
            metadata={"reader_action": reader_action} if reader_action else {},
        )
        return Publication(
            id=_stable_id("publication", canonical),
            work_id=_stable_id("work", canonical),
            source_id=self.id,
            title=title,
            source_url=stable_url,
            parts=(part,),
            coverage=Coverage.from_counts(0, None, unit="resources"),
            metadata={"reader_url_is_session_scoped": True},
        )

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
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
        raw_candidates = session.options.get("document_candidates") or ()
        candidates = [
            candidate
            for candidate in raw_candidates
            if isinstance(candidate, dict)
            and candidate.get("document_format") in {"pdf", "epub"}
            and (
                candidate.get("owner_page") is None
                or candidate.get("owner_page") is session.page
            )
        ]
        if not candidates:
            raise RuntimeError(
                "EBooksSource recognized the reader but no PDF or EPUB response "
                "was captured; generic fallback is intentionally disabled"
            )
        candidate = candidates[-1]
        locator = _candidate_url(candidate)
        document_format = str(candidate["document_format"])
        resource = Resource(
            id=_stable_id("resource", f"{part.id}:{document_format}"),
            kind=(ResourceKind.PDF if document_format == "pdf" else ResourceKind.EPUB),
            locator=locator,
            position=1,
            media_type=(
                "application/pdf"
                if document_format == "pdf"
                else "application/epub+zip"
            ),
            sensitive_locator=True,
            metadata={"network_document_format": document_format},
        )
        return ResourceSet((resource,), _coverage_from_candidate(candidate))
