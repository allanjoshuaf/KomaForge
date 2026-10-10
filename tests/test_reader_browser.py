from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from document_extractor.formats import find_chrome_executable
from document_extractor.library_state import LibraryState
from document_extractor.reader import ReaderDocument, ReaderServer


class ReaderBrowserTests(unittest.TestCase):
    def test_navigation_saves_and_resumes_persistent_progress(self):
        chrome = find_chrome_executable()
        if chrome is None:
            self.skipTest("Chrome unavailable")
        with tempfile.TemporaryDirectory() as temp, sync_playwright() as playwright:
            root = Path(temp)
            images = root / "images"
            images.mkdir()
            for number in range(1, 4):
                image = Image.new("RGB", (500, 800), "white")
                ImageDraw.Draw(image).text((80, 100), f"KomaForge - page {number}", fill="black")
                image.save(images / f"page-{number}.png")
            state = LibraryState(root / "state.sqlite")
            state.track("publication")
            state.set_progress("publication", "part", 2)

            def save(position, completed):
                state.set_progress("publication", "part", position, completed=completed)

            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 850}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                for target in (2, 3):
                    stored = LibraryState(state.path).progress("publication")[0]
                    server = ReaderServer(
                        ReaderDocument.from_path(images), title="Reading test",
                        start_position=stored.resource_position, progress_callback=save,
                    )
                    thread = threading.Thread(target=server.serve, kwargs={"open_browser": False}, daemon=True)
                    thread.start()
                    try:
                        page.goto(server.url)
                        page.wait_for_function("() => document.querySelector('#position').textContent === 'Page 2 / 3'")
                        if target == 3:
                            page.locator("#next").click()
                            page.wait_for_function("() => document.querySelector('#position').textContent === 'Page 3 / 3'")
                        page.wait_for_function("() => [...document.images].some(image => image.complete && image.naturalWidth > 0)")
                        screenshot = os.environ.get("KOMAFORGE_READER_SCREENSHOT")
                        if screenshot and target == 3:
                            page.screenshot(path=screenshot)
                        page.locator("#close").click()
                        page.wait_for_function("() => document.body.textContent.includes('Lecteur fermé')")
                    finally:
                        if thread.is_alive():
                            server.shutdown()
                        thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                    saved = LibraryState(state.path).progress("publication")[0]
                    self.assertEqual(saved.resource_position, target)
                    self.assertEqual(saved.completed, target == 3)
                self.assertEqual(errors, [])
            finally:
                browser.close()
