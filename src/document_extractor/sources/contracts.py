"""Small mandatory source contract with optional capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..models import (
    Confidence,
    Coverage,
    Part,
    Publication,
    Resource,
    UpdateResult,
    Work,
)


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Lightweight hints available while selecting a specialized adapter.

    The context deliberately contains no Playwright types.  A caller may match
    from the original URL alone, or add facts gathered during navigation.
    """

    final_url: str | None = None
    page_title: str | None = None
    content_type: str | None = None
    hints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("final_url", "page_title", "content_type"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)
        if not isinstance(self.hints, Mapping):
            raise ValueError("hints must be a mapping")
        object.__setattr__(self, "hints", dict(self.hints))


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: bool
    confidence: Confidence = Confidence.LOW
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.matched, bool):
            raise ValueError("matched must be a boolean")
        if not isinstance(self.confidence, Confidence):
            raise ValueError("confidence must be a Confidence")
        if self.reason is not None:
            _require_text(self.reason, "match reason")

    @classmethod
    def no_match(cls, reason: str | None = None) -> MatchResult:
        return cls(False, Confidence.LOW, reason)

    @classmethod
    def recognized(
        cls,
        reason: str,
        confidence: Confidence = Confidence.HIGH,
    ) -> MatchResult:
        return cls(True, confidence, reason)


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_id: str
    value: str
    url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.value, "reference value")
        if self.url is not None:
            _require_text(self.url, "reference url")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(slots=True)
class SourceSession:
    """Runtime services made available to an adapter by the application layer."""

    browser_context: object | None = None
    page: object | None = None
    request: object | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.options, Mapping):
            raise ValueError("options must be a mapping")
        self.options = dict(self.options)


@dataclass(frozen=True, slots=True)
class ResourceSet:
    resources: tuple[Resource, ...]
    coverage: Coverage

    def __post_init__(self) -> None:
        if not isinstance(self.resources, tuple) or not all(
            isinstance(resource, Resource) for resource in self.resources
        ):
            raise ValueError("resources must be a tuple of Resource instances")
        if not isinstance(self.coverage, Coverage):
            raise ValueError("coverage must be a Coverage")


@runtime_checkable
class SourceAdapter(Protocol):
    """Minimum contract for a source that recognizes publication URLs."""

    id: str
    name: str

    def match(self, url: str, context: MatchContext) -> MatchResult: ...

    def get_publication(
        self,
        reference: SourceReference,
        session: SourceSession,
    ) -> Publication: ...

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]: ...

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet: ...


@dataclass(frozen=True, slots=True)
class SearchPage:
    works: tuple[Work, ...]
    page: int
    has_next: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.works, tuple) or not all(
            isinstance(work, Work) for work in self.works
        ):
            raise ValueError("works must be a tuple of Work instances")
        if not isinstance(self.page, int) or isinstance(self.page, bool) or self.page < 1:
            raise ValueError("page must be an integer starting at 1")
        if not isinstance(self.has_next, bool):
            raise ValueError("has_next must be a boolean")


@runtime_checkable
class SearchCapability(Protocol):
    def search(
        self,
        query: str,
        filters: Mapping[str, Any],
        page: int,
        session: SourceSession,
    ) -> SearchPage: ...


@runtime_checkable
class BrowseCapability(Protocol):
    def popular(self, page: int, session: SourceSession) -> SearchPage: ...

    def latest(self, page: int, session: SourceSession) -> SearchPage: ...


@runtime_checkable
class UpdateCapability(Protocol):
    def check_updates(
        self,
        publication: Publication,
        known_parts: tuple[Part, ...],
        session: SourceSession,
    ) -> UpdateResult: ...
