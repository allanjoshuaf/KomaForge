"""Adapter for MGU Russian store product pages with no public reader."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from ..models import Confidence, Coverage, Part, PartKind, Publication
from ..paths import canonical_source_identity, clean_publication_title
from .catalog import SourceAccess, SourceMetadata, SourceStatus
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


class MguRussianStoreSource:
    id = "mgu-russian-store"
    name = "MGU Russian Store"
    metadata = SourceMetadata(
        languages=("ru", "en"),
        domains=("book.mgu-russian.com", "book-en.mgu-russian.com"),
        version="1",
        status=SourceStatus.DEGRADED,
        status_reason=(
            "product pages describe paid digital books but expose no public reader or file"
        ),
        access=SourceAccess.SOURCE_LIMITED,
        family_ids=("direct-document",),
        last_verified="2026-09-30",
    )

    def match(self, url: str, context: MatchContext) -> MatchResult:
        del context
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if host not in self.metadata.domains or "/tproduct/" not in parsed.path:
            return MatchResult.no_match("not an MGU Russian store product URL")
        return MatchResult.recognized(
            "official MGU Russian store product page",
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
            raise RuntimeError("MguRussianStoreSource requires a prepared browser page")
        source_url = reference.url or reference.value
        canonical = canonical_source_identity(source_url)
        raw_title = str(session.page.title() or "").strip()
        title = clean_publication_title(raw_title) or "MGU Russian publication"
        coverage = Coverage.from_counts(
            0,
            None,
            unit="resources",
            evidence="store product page",
            confidence=Confidence.HIGH,
            detail="the purchased digital files are delivered outside the product page",
        )
        part = Part(
            id=_stable_id("part", canonical),
            kind=PartKind.DOCUMENT,
            title=title,
            position=1,
            number="1",
            source_url=source_url,
            coverage=coverage,
            metadata={"access": "purchase_delivery"},
        )
        return Publication(
            id=_stable_id("publication", canonical),
            work_id=_stable_id("work", canonical),
            source_id=self.id,
            title=title,
            source_url=source_url,
            parts=(part,),
            coverage=coverage,
            metadata={"access": "purchase_delivery"},
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
        del part, session
        raise RuntimeError(
            "La fiche MGU Russian est une page d'achat, pas un lecteur : "
            "les fichiers électroniques sont livrés par e-mail après achat. "
            "KomaForge refuse d'utiliser l'image commerciale comme fausse page ; "
            "ouvrez plutôt le fichier ou le lien autorisé reçu avec la commande."
        )
