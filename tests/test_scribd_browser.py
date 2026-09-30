from __future__ import annotations

import unittest

from playwright.sync_api import sync_playwright

from document_extractor.formats import find_chrome_executable
from document_extractor.sources.scribd import (
    _access_gate_state,
    _hide_external_overlays,
    _png_ink_ratio,
)


class ScribdBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            launch_options = {"headless": True}
            chrome = find_chrome_executable()
            if chrome is not None:
                launch_options["executable_path"] = str(chrome)
            cls.browser = cls.playwright.chromium.launch(**launch_options)
        except Exception as exc:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chromium unavailable: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 900, "height": 700})

    def tearDown(self):
        self.page.close()

    def test_blur_on_page_ancestor_is_an_active_access_gate(self):
        self.page.set_content(
            """
            <main style="filter: blur(4px)">
              <section id="outer_page_1">Текст страницы</section>
            </main>
            <button>Unlock this document</button>
            """
        )

        state = _access_gate_state(self.page)

        self.assertTrue(state["active"])
        self.assertEqual(state["filtered"], ("outer_page_1",))
        self.assertIn("unlock this document", state["messages"])

    def test_dynamic_descendant_gate_is_detected_after_scroll(self):
        self.page.set_content(
            """
            <style>
              #outer_page_1, #outer_page_2 { width: 600px; height: 900px; }
              .blurred_page { filter: blur(5px); }
            </style>
            <section id="outer_page_1">Первая страница</section>
            <section id="outer_page_2">Вторая страница</section>
            <script>
              const target = document.querySelector('#outer_page_2');
              new IntersectionObserver(entries => {
                if (!entries.some(entry => entry.isIntersecting)) return;
                target.classList.add('blurred_page');
                const panel = document.createElement('div');
                panel.style.position = 'absolute';
                panel.innerHTML = '<button>Unlock the next 20 pages after an ad</button>';
                target.appendChild(panel);
              }).observe(target);
            </script>
            """
        )

        self.page.locator("#outer_page_2").scroll_into_view_if_needed()
        self.page.wait_for_function(
            "document.querySelector('#outer_page_2').classList.contains('blurred_page')"
        )
        state = _access_gate_state(self.page)

        self.assertTrue(state["active"])
        self.assertEqual(state["blurred"], ("outer_page_2",))
        self.assertIn("unlock the next", state["messages"])

    def test_external_chrome_is_hidden_without_hiding_document_ancestor(self):
        self.page.set_content(
            """
            <header id="external" style="position: fixed">Navigation</header>
            <main id="reader" style="position: sticky">
              <section id="outer_page_1">Россия — моя любовь</section>
            </main>
            """
        )

        hidden = _hide_external_overlays(self.page)

        self.assertEqual(hidden, 1)
        self.assertEqual(
            self.page.locator("#external").evaluate("node => getComputedStyle(node).visibility"),
            "hidden",
        )
        self.assertNotEqual(
            self.page.locator("#reader").evaluate("node => getComputedStyle(node).visibility"),
            "hidden",
        )

    def test_visual_check_distinguishes_blank_and_printed_pages(self):
        self.page.set_content(
            """
            <section id="blank" style="width: 800px; height: 1100px; background: white"></section>
            <section id="printed" style="width: 800px; height: 1100px; background: white">
              <h1 style="padding: 100px; color: black">Computer Networking</h1>
              <p style="padding: 0 100px; color: black">A top-down approach</p>
            </section>
            """
        )
        blank = self.page.locator("#blank").screenshot(type="png")
        printed = self.page.locator("#printed").screenshot(type="png")

        blank_ratio = _png_ink_ratio(self.page, blank)
        printed_ratio = _png_ink_ratio(self.page, printed)

        self.assertIsNotNone(blank_ratio)
        self.assertIsNotNone(printed_ratio)
        self.assertLess(blank_ratio, 0.0005)
        self.assertGreater(printed_ratio, 0.0005)


if __name__ == "__main__":
    unittest.main()
