from __future__ import annotations

import base64
import unittest

from document_extractor.application import load_source_publication, resolve_source
from document_extractor.models import CoverageStatus, ResourceKind
from document_extractor.sources import (
    SourceReference,
    SourceSession,
    build_default_registry,
)


SOURCE_URL = "https://fr.scribd.com/document/669933904/example"
PNG = b"\x89PNG\r\n\x1a\n" + b"test"


class FakeLocator:
    def __init__(self, page_number: int = 0):
        self.page_number = page_number
        self.first = self

    def get_attribute(self, name):
        if name == "content":
            return "Россия — моя любовь | Scribd"
        return None

    def scroll_into_view_if_needed(self, **kwargs):
        return None

    def inner_text(self, **kwargs):
        return "текст страницы с дополнительными словами" if self.page_number != 3 else ""

    def screenshot(self, **kwargs):
        return PNG + bytes([self.page_number])

    def wait_for(self, **kwargs):
        return None

    def evaluate(self, script):
        return {"x": 0, "y": 0, "width": 800, "height": 1100}


class FakeCDPSession:
    def send(self, method, params):
        return {"data": base64.b64encode(PNG).decode("ascii")}

    def detach(self):
        return None


class FakeContext:
    def new_cdp_session(self, page):
        return FakeCDPSession()


class FakePage:
    def __init__(self):
        self.hidden_overlays = False

    def evaluate(self, script):
        if "scribd_access_gate" in script:
            return {"active": False, "blurred": [], "messages": []}
        if "Array.from(document.querySelectorAll" in script:
            return [3, 1, 2, 2]
        if "data-komaforge-scribd-overlay" in script:
            self.hidden_overlays = True
            return 2
        return True

    def locator(self, selector):
        if selector.startswith("#outer_page_"):
            return FakeLocator(int(selector.rsplit("_", 1)[1]))
        return FakeLocator()

    def title(self):
        return "fallback"

    def wait_for_timeout(self, milliseconds):
        return None


class GatedPage(FakePage):
    def __init__(self, *, clears_after_prompt=False):
        super().__init__()
        self.clears_after_prompt = clears_after_prompt
        self.prompted = False

    def evaluate(self, script):
        if "scribd_access_gate" in script:
            active = not (self.clears_after_prompt and self.prompted)
            return {
                "active": active,
                "blurred": ["outer_page_2"] if active else [],
                "messages": ["unlock the next"] if active else [],
            }
        return super().evaluate(script)

    def wait_for_function(self, script, timeout):
        raise RuntimeError("gate remains active")


class VisualStatsPage(FakePage):
    def __init__(self, ratios):
        super().__init__()
        self.context = FakeContext()
        self.ratios = iter(ratios)

    def evaluate(self, script, *args):
        if "scribd_png_visual_stats" in script:
            return {"ratio": next(self.ratios)}
        return super().evaluate(script)


class ScribdSourceTests(unittest.TestCase):
    def test_document_url_is_routed_to_a_specialized_adapter(self):
        route = resolve_source(SOURCE_URL)

        self.assertTrue(route.specialized)
        self.assertEqual(route.adapter.id, "scribd")
        self.assertIsNone(
            build_default_registry().resolve("https://fr.scribd.com/explore")
        )

    def test_layered_pages_are_rendered_as_complete_embedded_pngs(self):
        route = resolve_source(SOURCE_URL)
        page = FakePage()
        session = SourceSession(page=page)
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, SOURCE_URL, SOURCE_URL),
            session,
        )
        resource_set = route.adapter.get_resources(publication.parts[0], session)

        self.assertEqual(publication.title, "Россия — моя любовь")
        self.assertEqual(resource_set.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(resource_set.coverage.available, 3)
        self.assertEqual(resource_set.coverage.expected, 3)
        self.assertEqual(
            [resource.position for resource in resource_set.resources],
            [1, 2, 3],
        )
        self.assertTrue(
            all(resource.kind is ResourceKind.IMAGE for resource in resource_set.resources)
        )
        self.assertTrue(
            all(
                resource.metadata["_embedded_data"].startswith(b"\x89PNG")
                for resource in resource_set.resources
            )
        )
        self.assertGreater(
            resource_set.resources[0].metadata["rendered_text_characters"],
            0,
        )
        self.assertEqual(
            resource_set.resources[2].metadata["rendered_text_characters"],
            0,
        )
        self.assertTrue(page.hidden_overlays)

    def test_access_gate_is_not_archived_as_a_successful_page(self):
        route = resolve_source(SOURCE_URL)
        page = GatedPage()
        session = SourceSession(page=page)
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, SOURCE_URL, SOURCE_URL),
            session,
        )

        with self.assertRaisesRegex(RuntimeError, "refuse d'archiver"):
            route.adapter.get_resources(publication.parts[0], session)

    def test_manual_access_gate_completion_can_resume_rendering(self):
        route = resolve_source(SOURCE_URL)
        page = GatedPage(clears_after_prompt=True)

        def prompt(message):
            self.assertIn("publicité", message)
            page.prompted = True

        session = SourceSession(page=page, options={"access_gate_prompt": prompt})
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, SOURCE_URL, SOURCE_URL),
            session,
        )
        resources = route.adapter.get_resources(publication.parts[0], session)

        self.assertEqual(resources.coverage.status, CoverageStatus.COMPLETE)
        self.assertTrue(page.prompted)

    def test_blank_cdp_capture_uses_locator_fallback(self):
        route = resolve_source(SOURCE_URL)
        page = VisualStatsPage([0.0, 0.02, 0.0, 0.02, 0.0, 0.02])
        session = SourceSession(page=page)
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, SOURCE_URL, SOURCE_URL),
            session,
        )

        resources = route.adapter.get_resources(publication.parts[0], session)

        self.assertEqual(resources.coverage.status, CoverageStatus.COMPLETE)
        self.assertEqual(
            [resource.metadata["capture_method"] for resource in resources.resources],
            ["locator-fallback", "locator-fallback", "cdp"],
        )

    def test_dom_text_with_persistently_blank_render_is_rejected(self):
        route = resolve_source(SOURCE_URL)
        page = VisualStatsPage([0.0, 0.0])
        session = SourceSession(page=page)
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, SOURCE_URL, SOURCE_URL),
            session,
        )

        with self.assertRaisesRegex(RuntimeError, "visuellement vide"):
            route.adapter.get_resources(publication.parts[0], session)


if __name__ == "__main__":
    unittest.main()
