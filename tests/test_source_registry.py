from __future__ import annotations

import unittest

from document_extractor.models import Confidence, Coverage, Part, Publication
from document_extractor.sources import (
    AmbiguousSourceError,
    DuplicateSourceError,
    MatchContext,
    MatchResult,
    ResourceSet,
    SourceMatchError,
    SourceReference,
    SourceRegistry,
    SourceSession,
)


class FakeAdapter:
    name = "Fake"

    def __init__(
        self,
        source_id: str,
        result: MatchResult,
        *,
        match_error: Exception | None = None,
    ) -> None:
        self.id = source_id
        self._result = result
        self._match_error = match_error

    def match(self, url: str, context: MatchContext) -> MatchResult:
        if self._match_error:
            raise self._match_error
        return self._result

    def get_publication(
        self,
        reference: SourceReference,
        session: SourceSession,
    ) -> Publication:
        raise NotImplementedError

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
        raise NotImplementedError

    def get_resources(
        self,
        part: Part,
        session: SourceSession,
    ) -> ResourceSet:
        raise NotImplementedError


class SourceRegistryTests(unittest.TestCase):
    def test_no_specialized_match_leaves_the_generic_decision_to_the_caller(self):
        registry = SourceRegistry(
            (FakeAdapter("known", MatchResult.no_match("different host")),)
        )

        self.assertIsNone(registry.resolve("https://unknown.example/book"))

    def test_highest_confidence_specialized_adapter_wins(self):
        registry = SourceRegistry(
            (
                FakeAdapter(
                    "possible",
                    MatchResult.recognized("page pattern", Confidence.MEDIUM),
                ),
                FakeAdapter(
                    "exact",
                    MatchResult.recognized("official host", Confidence.HIGH),
                ),
            )
        )

        resolution = registry.resolve("https://reader.example/book")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.adapter.id, "exact")
        self.assertEqual(resolution.match.reason, "official host")

    def test_equal_specialized_matches_are_reported_as_ambiguous(self):
        registry = SourceRegistry(
            (
                FakeAdapter("one", MatchResult.recognized("host")),
                FakeAdapter("two", MatchResult.recognized("host")),
            )
        )

        with self.assertRaisesRegex(AmbiguousSourceError, "one, two"):
            registry.resolve("https://reader.example/book")

    def test_matcher_failure_is_never_treated_as_no_match(self):
        registry = SourceRegistry(
            (
                FakeAdapter(
                    "broken",
                    MatchResult.no_match(),
                    match_error=RuntimeError("broken metadata"),
                ),
            )
        )

        with self.assertRaisesRegex(SourceMatchError, "broken metadata"):
            registry.resolve("https://reader.example/book")

    def test_duplicate_source_ids_are_rejected(self):
        adapter = FakeAdapter("same", MatchResult.no_match())
        registry = SourceRegistry((adapter,))

        with self.assertRaisesRegex(DuplicateSourceError, "same"):
            registry.register(adapter)


if __name__ == "__main__":
    unittest.main()
