from __future__ import annotations

import unittest

from document_extractor.application import plan_publication_updates, resolve_source
from document_extractor.models import Coverage, Part, PartKind, Publication
from document_extractor.sources import MatchContext, MatchResult, SourceSession
from document_extractor.updates import compare_part_updates


class UpdatingSource:
    id = "updates"
    name = "Updates"

    def match(self, url, context: MatchContext):
        return MatchResult.recognized("test source")

    def get_publication(self, reference, session):
        raise NotImplementedError

    def get_parts(self, publication, session):
        return publication.parts

    def get_resources(self, part, session):
        raise NotImplementedError

    def check_updates(self, publication, known_parts, session):
        return compare_part_updates(publication, known_parts, publication.parts)


def publication(parts, *, source_id="updates", url="https://example.test/work"):
    return Publication(
        id="publication",
        work_id="work",
        source_id=source_id,
        title="Example",
        source_url=url,
        parts=parts,
        coverage=Coverage.from_counts(len(parts), len(parts), unit="parts"),
    )


def chapter(number):
    return Part(
        id=f"chapter-{number}",
        kind=PartKind.CHAPTER,
        title=f"Chapter {number}",
        position=number,
        number=str(number),
        source_url=f"https://example.test/work/{number}",
    )


class SourceRoutingTests(unittest.TestCase):
    def test_known_source_is_selected_once_as_specialized(self):
        route = resolve_source("https://www.calameo.com/read/abc_123")

        self.assertTrue(route.specialized)
        self.assertEqual(route.adapter.id, "calameo")

    def test_unknown_http_site_uses_the_explicit_generic_fallback(self):
        route = resolve_source("https://example.test/publication")

        self.assertFalse(route.specialized)
        self.assertEqual(route.adapter.id, "generic-web")

    def test_non_web_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no KomaForge source"):
            resolve_source("file:///tmp/book.pdf")


class ApplicationUpdateTests(unittest.TestCase):
    def test_plans_new_parts_with_an_update_capable_adapter(self):
        known = publication(
            (chapter(1),),
            url="https://example.test/work?utm_source=old",
        )
        current = publication((chapter(1), chapter(2)))

        result = plan_publication_updates(
            known,
            current,
            SourceSession(),
            adapter=UpdatingSource(),
        )

        self.assertEqual([part.number for part in result.parts], ["2"])

    def test_rejects_a_different_publication_identity(self):
        known = publication((chapter(1),))
        current = publication(
            (chapter(1),),
            url="https://example.test/other",
        )

        with self.assertRaisesRegex(ValueError, "different identities"):
            plan_publication_updates(
                known,
                current,
                SourceSession(),
                adapter=UpdatingSource(),
            )


if __name__ == "__main__":
    unittest.main()
