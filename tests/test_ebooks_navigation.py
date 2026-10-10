from __future__ import annotations

from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from document_extractor.ebooks_navigation import discover_linked_reader


class PreviewPage:
    """A product whose frontend and response advance on a virtual clock."""

    url = "https://www.ebooks.com/en-us/book/210629805/physics/author/"
    frames = []
    reader_url = "https://reader.ebooks.com/preview?uid=test"

    def __init__(self, *, ready_at=0, replace_at=None, launch_delay=None):
        self.now = 0
        self.ready_at = ready_at
        self.replace_at = replace_at
        self.launch_delay = launch_delay
        self.launch_at = None
        self.clicks = []
        self.listeners = {}
        self.context = SimpleNamespace(pages=[self])

    def marker(self):
        replaced = self.replace_at is not None and self.now >= self.replace_at
        return "replacement" if replaced else "initial"

    def evaluate(self, _script):
        if self.now < self.ready_at:
            return []
        return [{"marker": self.marker(), "label": "Preview", "href": ""}]

    def on(self, event, callback):
        self.listeners[event] = callback

    def remove_listener(self, event, callback):
        assert self.listeners.pop(event) is callback

    def is_closed(self):
        return False

    def locator(self, selector):
        page = self

        class Control:
            @property
            def first(self):
                return self

            def click(self, **_kwargs):
                if page.marker() not in selector:
                    raise RuntimeError("The original control was replaced")
                page.clicks.append(page.now)
                if page.replace_at is not None and page.now < page.replace_at:
                    return  # The initial unhydrated control has no click handler.
                if page.launch_at is None:
                    page.launch_at = page.now + (page.launch_delay or 0)

            def evaluate(self, _script):
                self.click()

        return Control()

    def wait_for_timeout(self, milliseconds):
        self.now += milliseconds / 1000
        if self.launch_at is not None and self.now >= self.launch_at:
            response = SimpleNamespace(
                url="https://reader-backend.ebooks.com/api/reader-instance/preview-launch",
                ok=True,
                json=lambda: {"ok": True, "previewUrl": self.reader_url},
            )
            self.listeners["response"](response)
            self.launch_at = None


class EbooksPreviewTimingTests(unittest.TestCase):
    def discover(self, page):
        with patch("document_extractor.ebooks_navigation.time.monotonic", side_effect=lambda: page.now):
            return discover_linked_reader(page.context, page)

    def assert_reader(self, page):
        self.assertEqual(self.discover(page), {"url": page.reader_url, "action": "Preview"})
        self.assertFalse(page.listeners)

    def test_waits_for_delayed_preview_button(self):
        page = PreviewPage(ready_at=2)
        self.assert_reader(page)
        self.assertGreaterEqual(page.clicks[0], 2)

    def test_rescans_preview_control_replaced_during_hydration(self):
        page = PreviewPage(replace_at=2)
        self.assert_reader(page)
        self.assertEqual(len(page.clicks), 2)

    def test_accepts_slow_preview_launch_response(self):
        page = PreviewPage(launch_delay=12)
        self.assert_reader(page)
        self.assertGreaterEqual(page.now, 12)

    def test_absent_preview_remains_bounded(self):
        page = PreviewPage(ready_at=100)
        self.assertIsNone(self.discover(page))
        self.assertLessEqual(page.now, 5)
        self.assertFalse(page.clicks)

    def test_launch_that_never_completes_remains_bounded(self):
        page = PreviewPage(launch_delay=100)
        result = self.discover(page)
        self.assertIsNone(result["url"])
        self.assertIn("error", result)
        self.assertLessEqual(page.now, 30)
        self.assertFalse(page.listeners)


@unittest.skipUnless(os.environ.get("RUN_EXTRACTOR_E2E") == "1", "test navigateur facultatif")
class EbooksPreviewBrowserTests(unittest.TestCase):
    def test_delayed_and_replaced_controls_in_real_browser(self):
        from playwright.sync_api import sync_playwright
        from document_extractor.formats import find_chrome_executable

        chrome = find_chrome_executable()
        if not chrome:
            self.skipTest("Chrome absent")
        # Intercept every request: this fixture never contacts the live site.
        html = """<!DOCTYPE html><html><body><script>
        const launch = () => fetch(
            'https://reader-backend.ebooks.com/api/reader-instance/preview-launch');
        setTimeout(() => {
            const initial = document.createElement('button');
            initial.textContent = 'Preview';
            document.body.append(initial);
            setTimeout(() => {
                const replacement = document.createElement('button');
                replacement.textContent = 'Preview';
                replacement.onclick = launch;
                initial.replaceWith(replacement);
            }, 750);
        }, 750);
        </script></body></html>"""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            try:
                context = browser.new_context()

                def serve(route):
                    if route.request.url == PreviewPage.url:
                        route.fulfill(status=200, content_type="text/html", body=html)
                    elif route.request.url.endswith("/api/reader-instance/preview-launch"):
                        route.fulfill(status=200, json={"ok": True, "previewUrl": PreviewPage.reader_url},
                                      headers={"Access-Control-Allow-Origin": "*"})
                    else:
                        route.abort()

                context.route("**/*", serve)
                page = context.new_page()
                page.goto(PreviewPage.url)
                self.assertEqual(discover_linked_reader(context, page),
                                 {"url": PreviewPage.reader_url, "action": "preview"})
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
