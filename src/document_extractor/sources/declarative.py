"""Declarative third-party sources backed only by built-in reader strategies."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse

from ..models import Confidence, Part, Publication
from ..updates import compare_part_updates
from .catalog import (
    SourceAccess,
    SourceIntegration,
    SourceMetadata,
    SourceStatus,
)
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceReference,
    SourceSession,
    UpdateResult,
)
from .generic import GenericWebSource


class DeclarativeWebSource:
    """Route declared domains through GenericWebSource without loading code."""

    def __init__(
        self,
        *,
        source_id: str,
        name: str,
        version: str,
        languages: tuple[str, ...],
        domains: tuple[str, ...],
        network_domains: tuple[str, ...],
        families: tuple[str, ...],
    ) -> None:
        self.id = source_id
        self.name = name
        self.domains = domains
        self.network_domains = network_domains
        self.metadata = SourceMetadata(
            languages=languages,
            domains=domains,
            version=version,
            status=SourceStatus.EXPERIMENTAL,
            status_reason="declarative package using built-in generic strategies",
            integration=SourceIntegration.GENERIC,
            access=SourceAccess.VARIABLE,
            family_ids=families,
        )
        self._generic = GenericWebSource()

    def match(self, url: str, context: MatchContext) -> MatchResult:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            return MatchResult.no_match("not an HTTP(S) publication URL")
        if not any(
            host == domain or host.endswith(f".{domain}")
            for domain in self.domains
        ):
            return MatchResult.no_match("domain is not declared by this package")
        return MatchResult.recognized(
            "domain declared by an enabled declarative source package",
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
        generic_reference = replace(reference, source_id=self._generic.id)
        publication = self._generic.get_publication(generic_reference, session)
        return replace(
            publication,
            source_id=self.id,
            metadata={
                **publication.metadata,
                "declarative_source": self.id,
            },
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
        return self._generic.get_parts(
            replace(publication, source_id=self._generic.id),
            session,
        )

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        return self._generic.get_resources(part, session)


class DeclarativeUpdateWebSource(DeclarativeWebSource):
    """Declarative source that explicitly opts into generic update checks."""

    def check_updates(
        self,
        publication: Publication,
        known_parts: tuple[Part, ...],
        session: SourceSession,
    ) -> UpdateResult:
        current_parts = self.get_parts(publication, session)
        return compare_part_updates(publication, known_parts, current_parts)
