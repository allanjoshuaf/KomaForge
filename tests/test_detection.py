from __future__ import annotations

import importlib.util
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from document_extractor.detection import (
    _auto_group,
    discover_linked_reader,
    is_ebooks_product_url,
    looks_like_chapter_url,
    normalize_chapter_candidates,
    normalize_manga_up_catalog,
    normalize_selectable_part_candidates,
    normalize_selector_input,
    select_chapters,
    wait_for_access_interstitial,
)
from document_extractor.engine import (
    ChapterTask,
    _complete_access_check,
    _ask_interactive_detached_recovery,
    _fetch_pdf_in_ranges,
    download_pages,
    inspect_detached_page_trees,
    navigate_to_source,
    recover_detached_page_tree,
    resolve_part_selection,
    run,
    trusted_selected_resource_hosts,
)
from tests.mock_site import DETACHED_TREE_PDF, NETWORK_EPUB, PNG, SVG
from tests.mock_site import MockDocumentHandler


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        _type, error, _traceback = sys.exc_info()
        if isinstance(error, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class SelectorInputTests(unittest.TestCase):
    def test_css_selector_is_unchanged(self):
        self.assertEqual(normalize_selector_input("img.ts-main-image"), "img.ts-main-image")

    def test_html_snippet_is_converted_to_css(self):
        self.assertEqual(
            normalize_selector_input('<img class="ts-main-image lazy" ...>'),
            "img.ts-main-image.lazy",
        )


class ChapterDiscoveryTests(unittest.TestCase):
    def test_recognizes_when_the_input_is_already_a_chapter(self):
        self.assertTrue(
            looks_like_chapter_url("https://example.test/manga/demo/chapter-12.5")
        )
        self.assertFalse(looks_like_chapter_url("https://example.test/manga/demo"))

    def test_recognizes_ebooks_product_pages_only(self):
        self.assertTrue(
            is_ebooks_product_url(
                "https://www.ebooks.com/en-us/book/347114076/the-demon-star/"
            )
        )
        self.assertTrue(is_ebooks_product_url("https://ebooks.com/book/123/title/"))
        self.assertFalse(
            is_ebooks_product_url("https://reader.ebooks.com/preview?uid=demo")
        )
        self.assertFalse(is_ebooks_product_url("https://example.test/book/123/title"))

    def test_ebooks_product_prefers_explicit_reader_link(self):
        class FakePage:
            url = "https://www.ebooks.com/en-us/book/347114076/the-demon-star/"

            @staticmethod
            def evaluate(_script):
                return {
                    "marker": "reader-entry-test",
                    "label": "Preview",
                    "href": "https://reader.ebooks.com/preview?uid=authorized-test",
                }

        result = discover_linked_reader(object(), FakePage())

        self.assertEqual(
            result,
            {
                "url": "https://reader.ebooks.com/preview?uid=authorized-test",
                "action": "Preview",
            },
        )

    def test_ebooks_product_uses_preview_launch_response(self):
        reader_url = (
            "https://reader.ebooks.com/preview?uid=preview-test&reqid=7"
        )

        class FakeResponse:
            url = (
                "https://reader-backend.ebooks.com/"
                "api/reader-instance/preview-launch"
            )
            ok = True

            @staticmethod
            def json():
                return {"ok": True, "previewUrl": reader_url}

        class FakeControl:
            def __init__(self, page):
                self.page = page

            @property
            def first(self):
                return self

            def click(self, **_kwargs):
                self.page.callback(FakeResponse())

        class FakePage:
            url = "https://www.ebooks.com/en-us/book/347114076/the-demon-star/"
            frames = []

            def evaluate(self, _script):
                return {
                    "marker": "reader-entry-test",
                    "label": "Preview",
                    "href": "",
                }

            def on(self, _event, callback):
                self.callback = callback

            def remove_listener(self, _event, callback):
                self.removed_callback = callback

            def locator(self, _selector):
                return FakeControl(self)

            @staticmethod
            def wait_for_timeout(_milliseconds):
                return None

            @staticmethod
            def is_closed():
                return False

        page = FakePage()
        context = SimpleNamespace(pages=[page])

        result = discover_linked_reader(context, page)

        self.assertEqual(result, {"url": reader_url, "action": "Preview"})
        self.assertIs(page.removed_callback, page.callback)

    def test_prefers_a_numbered_page_family_over_reader_noise(self):
        candidates = []
        for index in range(161):
            candidates.append(
                {
                    "position": index + 1,
                    "url": f"https://proxy.test/img?url=/book/1/{index}.webp",
                    "urlPattern": "https://proxy.test/img?url=/book/#/#.webp",
                    "classes": [],
                    "parentClasses": ["reader-page"],
                    "attributes": [],
                    "score": 13,
                    "decorative": False,
                }
            )
        for index in range(12):
            candidates.append(
                {
                    "position": 162 + index,
                    "url": f"https://proxy.test/img?url=/thumb/recommendation-{index}.webp",
                    "urlPattern": (
                        f"https://proxy.test/img?url=/thumb/recommendation-{index}.webp"
                    ),
                    "classes": [],
                    "parentClasses": ["reader-page"],
                    "attributes": [],
                    "score": 6,
                    "decorative": False,
                }
            )

        selected, source = _auto_group(candidates, expected=177)

        self.assertEqual(len(selected), 161)
        self.assertEqual(source, "motif d'URL répété")
        self.assertTrue(all("/book/" in item["url"] for item in selected))

    def test_keeps_same_site_chapters_and_orders_them_numerically(self):
        chapters = normalize_chapter_candidates(
            [
                {"title": "Chapitre 10", "url": "/manga/demo/chapter-10"},
                {"title": "Chapitre 2", "url": "/manga/demo/chapter-2#reader"},
                {"title": "Chapitre 1", "url": "/manga/demo/chapter-1"},
                {"title": "Chapitre 99", "url": "https://other.test/chapter-99"},
            ],
            "https://example.test/manga/demo",
        )

        self.assertEqual([chapter.number for chapter in chapters], ["1", "2", "10"])
        self.assertEqual(chapters[1].url, "https://example.test/manga/demo/chapter-2")

    def test_rejects_previous_next_navigation_as_too_ambiguous(self):
        chapters = normalize_chapter_candidates(
            [
                {"title": "Chapitre 4", "url": "/manga/demo/chapter-4"},
                {"title": "Chapitre 6", "url": "/manga/demo/chapter-6"},
            ],
            "https://example.test/manga/demo/chapter-5",
        )
        self.assertEqual(chapters, [])

    def test_selects_ranges_without_changing_reading_order(self):
        chapters = normalize_chapter_candidates(
            [
                {"title": f"Chapitre {number}", "url": f"/chapter-{number}"}
                for number in range(1, 7)
            ],
            "https://example.test/work",
        )
        selected = select_chapters(chapters, "2-3,5")
        self.assertEqual([chapter.number for chapter in selected], ["2", "3", "5"])

    def test_rejects_a_chapter_outside_the_detected_work(self):
        chapters = normalize_chapter_candidates(
            [
                {"title": f"Chapitre {number}", "url": f"/chapter-{number}"}
                for number in range(1, 4)
            ],
            "https://example.test/work",
        )
        with self.assertRaisesRegex(ValueError, "hors plage"):
            select_chapters(chapters, "4")

    def test_recognizes_a_numbered_volume_menu(self):
        parts = normalize_selectable_part_candidates(
            [
                {
                    "selector": "#selectParts",
                    "options": [
                        {"title": "Volume 10", "value": "v10"},
                        {"title": "Volume 2", "value": "v2"},
                        {"title": "Volume 1", "value": "v1"},
                    ],
                },
                {
                    "selector": "#readingSpeed",
                    "options": [
                        {"title": "Vitesse x1", "value": "1"},
                        {"title": "Vitesse x2", "value": "2"},
                    ],
                },
            ]
        )

        self.assertEqual([part.number for part in parts], ["1", "2", "10"])
        self.assertEqual([part.value for part in parts], ["v1", "v2", "v10"])
        self.assertTrue(all(part.kind == "volume" for part in parts))

    def test_interactive_collection_defaults_to_only_the_first_part(self):
        parts = [
            ChapterTask(
                index=index,
                number=str(index),
                title=f"Volume {index}",
                source_url="https://example.test/work",
                kind="volume",
            )
            for index in range(1, 4)
        ]
        with patch("builtins.input", return_value=""):
            selected = resolve_part_selection(parts, "ask", "volume")
        self.assertEqual([part.index for part in selected], [1])

    def test_interactive_source_limited_catalog_can_default_to_all_parts(self):
        parts = [
            ChapterTask(
                index=index,
                number=f"1 -{index}",
                title=f"Chapter 1 -{index}",
                source_url=f"https://example.test/work/{index}",
                kind="chapter",
            )
            for index in range(1, 4)
        ]
        with patch("builtins.input", return_value=""):
            selected = resolve_part_selection(
                parts,
                "ask",
                "chapter",
                default_expression="all",
            )
        self.assertEqual([part.index for part in selected], [1, 2, 3])

    def test_manga_up_catalog_separates_free_parts_from_full_catalog(self):
        chapters = [
            {
                "id": 10761,
                "mainName": "Chapter 2 -1",
                "subName": "The Price of Life",
                "price": 40,
            },
            {
                "id": 10760,
                "mainName": "Chapter 1 -3",
                "subName": "The Two Alchemists",
                "price": None,
                "consumptionType": 3,
            },
            {
                "id": 10759,
                "mainName": "Chapter 1 -2",
                "subName": "The Two Alchemists",
                "price": None,
                "consumptionType": 3,
            },
            {
                "id": 10758,
                "mainName": "Chapter 1 -1",
                "subName": "The Two Alchemists",
                "price": None,
                "consumptionType": 3,
            },
        ]
        payload = {"props": {"pageProps": {"data": {"chapters": chapters}}}}

        catalog = normalize_manga_up_catalog(
            payload,
            "https://global.manga-up.com/manga/126?utm_source=test",
        )

        self.assertIsNotNone(catalog)
        self.assertEqual(catalog.total_count, 4)
        self.assertEqual(catalog.accessible_count, 3)
        self.assertTrue(catalog.access_limited)
        self.assertEqual(
            [chapter.number for chapter in catalog.chapters],
            ["1 -1", "1 -2", "1 -3"],
        )
        self.assertEqual(
            [chapter.url for chapter in catalog.chapters],
            [
                "https://global.manga-up.com/manga/126/10758",
                "https://global.manga-up.com/manga/126/10759",
                "https://global.manga-up.com/manga/126/10760",
            ],
        )


class FakePage:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.url = "about:blank"
        self.closed = False

    def goto(self, url, **_kwargs):
        self.calls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.url = outcome
        return object()

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, pages):
        self.pages_to_create = list(pages)

    def new_page(self):
        return self.pages_to_create.pop(0)


class NavigationRecoveryTests(unittest.TestCase):
    def test_access_check_tolerates_navigation_context_replacement(self):
        class NavigatingPage:
            def __init__(self):
                self.calls = 0

            def evaluate(self, _script):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError(
                        "Execution context was destroyed, most likely because "
                        "of a navigation"
                    )
                return {"title": "Livre", "body": "Contenu prêt"}

            @staticmethod
            def wait_for_timeout(_milliseconds):
                return None

        result = wait_for_access_interstitial(NavigatingPage(), timeout_ms=1_000)

        self.assertTrue(result["passed"])
        self.assertFalse(result["encountered"])

    def test_interactive_challenge_requests_visible_user_completion(self):
        args = SimpleNamespace(interactive=True, wait_for_user=False)
        expected = {"passed": True, "encountered": True, "waited_ms": 0}
        with patch(
            "document_extractor.engine.access_interstitial_state",
            return_value={"active": True, "title": "Just a moment"},
        ), patch(
            "document_extractor.engine.wait_for_access_interstitial",
            return_value=expected,
        ), patch("builtins.input", return_value="") as prompt:
            result = _complete_access_check(object(), args)

        self.assertEqual(result, expected)
        prompt.assert_called_once()

    def test_transient_navigation_error_is_retried_in_a_clean_page(self):
        url = "https://example.test/book"
        failed = FakePage([RuntimeError("net::ERR_CONNECTION_RESET")])
        recovered = FakePage([url])

        result = navigate_to_source(FakeContext([recovered]), failed, url, retries=2)

        self.assertIs(result, recovered)
        self.assertTrue(failed.closed)
        self.assertEqual(recovered.calls, [url])

    def test_ssl_recovery_warms_only_origin_then_reopens_target(self):
        url = "https://www.calameo.com/read/book-id?private=value"
        failed = FakePage([RuntimeError("net::ERR_SSL_PROTOCOL_ERROR")])
        recovered = FakePage(["https://www.calameo.com/", url])

        result = navigate_to_source(FakeContext([recovered]), failed, url)

        self.assertIs(result, recovered)
        self.assertTrue(failed.closed)
        self.assertEqual(
            recovered.calls,
            ["http://www.calameo.com/", url],
        )

    def test_ssl_recovery_rejects_a_redirect_to_another_host(self):
        url = "https://example.test/book"
        failed = FakePage([RuntimeError("net::ERR_SSL_PROTOCOL_ERROR")])
        unsafe = FakePage(["https://different.test/"])

        with self.assertRaisesRegex(RuntimeError, "Impossible d'ouvrir"):
            navigate_to_source(FakeContext([unsafe]), failed, url, retries=1)

        self.assertEqual(unsafe.calls, ["http://example.test/"])


class ResumeTests(unittest.TestCase):
    def test_existing_svg_is_cleaned_before_it_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            images = Path(temp)
            existing = images / "page-0001.svg"
            existing.write_bytes(SVG)
            (images / ".komaforge-resume.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "pages": {
                            "1": {
                                "url": "https://example.test/page-1.svg",
                                "file": existing.name,
                                "sha256": hashlib.sha256(SVG).hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            results, missing = download_pages(
                context=None,
                pages=[{"page": 1, "url": "https://example.test/page-1.svg"}],
                images_dir=images,
                source_url="https://example.test/book",
                allowed_hosts={"example.test"},
                retries=1,
                max_image_bytes=1024 * 1024,
                watermark_policy="remove",
                watermark_texts=[],
            )

            self.assertEqual(missing, [])
            self.assertEqual(results[0]["status"], "cleaned-existing")
            self.assertEqual(results[0]["watermarks_removed"], 1)
            self.assertNotIn(b"SPECIMEN", existing.read_bytes())

    def test_stale_page_number_is_replaced_when_its_source_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            images = Path(temp)
            stale = images / "page-0001.gif"
            stale.write_bytes(b"GIF89a-stale-placeholder")
            image_url = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")

            results, missing = download_pages(
                context=None,
                pages=[{"page": 1, "url": image_url}],
                images_dir=images,
                source_url="https://example.test/book",
                allowed_hosts={"example.test"},
                retries=1,
                max_image_bytes=1024 * 1024,
                watermark_policy="remove",
                watermark_texts=[],
            )

            self.assertEqual(missing, [])
            self.assertEqual(results[0]["file"], "page-0001.png")
            self.assertFalse(stale.exists())
            self.assertEqual((images / "page-0001.png").read_bytes(), PNG)


class SelectedResourceHostTests(unittest.TestCase):
    def test_trusts_only_a_repeated_https_host_in_selected_pages(self):
        pages = [
            {"page": index, "url": f"https://cdn.example.net/page-{index}.webp"}
            for index in range(1, 10)
        ]
        pages.extend(
            [
                {"page": 10, "url": "https://reader.example.org/placeholder.gif"},
                {"page": 11, "url": "https://ads.example.net/banner.gif"},
            ]
        )

        trusted = trusted_selected_resource_hosts(
            pages,
            "https://reader.example.org/book",
            {"reader.example.org"},
        )

        self.assertEqual(trusted, {"cdn.example.net": 9})

    def test_does_not_trust_http_or_an_isolated_external_resource(self):
        pages = [
            {"page": 1, "url": "http://cdn.example.net/page-1.webp"},
            {"page": 2, "url": "https://unknown.example.net/page-2.webp"},
            {"page": 3, "url": "https://reader.example.org/page-3.webp"},
        ]

        trusted = trusted_selected_resource_hosts(
            pages,
            "https://reader.example.org/book",
            {"reader.example.org"},
        )

        self.assertEqual(trusted, {})


class PdfTransportTests(unittest.TestCase):
    def test_large_pdf_is_reassembled_from_verified_byte_ranges(self):
        payload = b"%PDF-test-payload"

        class FakeResponse:
            status = 206

            def __init__(self, body):
                self._body = body

            def body(self):
                return self._body

        class FakeRequestContext:
            def __init__(self):
                self.ranges = []

            def fetch(self, _url, *, method, headers, timeout):
                self.assertions = (method, timeout)
                value = headers["range"].removeprefix("bytes=")
                start, end = (int(item) for item in value.split("-", 1))
                self.ranges.append((start, end))
                return FakeResponse(payload[start : end + 1])

        class FakeContext:
            def __init__(self):
                self.request = FakeRequestContext()

        class FakeRequest:
            url = "https://example.test/book.pdf"

        context = FakeContext()
        with patch("document_extractor.engine.PDF_RANGE_CHUNK_BYTES", 4):
            recovered = _fetch_pdf_in_ranges(
                context, FakeRequest(), {"cookie": "session=test"}, len(payload)
            )

        self.assertEqual(recovered, payload)
        self.assertEqual(
            context.request.ranges,
            [(0, 3), (4, 7), (8, 11), (12, 15), (16, 16)],
        )
        self.assertEqual(context.request.assertions, ("GET", 60_000))

    def test_interactive_recovery_is_offered_only_for_one_complete_tree(self):
        args = type("Args", (), {"interactive": True, "inspect": False})()
        diagnostics = {
            "detached_ordered_page_trees": [
                {
                    "declared_count": 10,
                    "is_structurally_complete": True,
                }
            ]
        }
        with patch("builtins.input", return_value="oui") as prompt:
            accepted = _ask_interactive_detached_recovery(args, diagnostics, 10)
        self.assertTrue(accepted)
        prompt.assert_called_once()

        with patch("builtins.input") as prompt:
            refused = _ask_interactive_detached_recovery(args, diagnostics, 11)
        self.assertFalse(refused)
        prompt.assert_not_called()


@unittest.skipUnless(os.environ.get("RUN_EXTRACTOR_E2E") == "1", "test navigateur facultatif")
class EndToEndDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_temp = tempfile.TemporaryDirectory(
            prefix="komaforge-e2e-profile-"
        )
        cls.profile_environment = patch.dict(
            os.environ,
            {"KOMAFORGE_PROFILE_DIR": cls.profile_temp.name},
        )
        cls.profile_environment.start()
        cls.server = QuietThreadingHTTPServer(("127.0.0.1", 0), MockDocumentHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.profile_environment.stop()
        cls.profile_temp.cleanup()

    def test_fully_automatic_extraction(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((Path(temp) / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["publication"]["type"], "document")
            self.assertEqual(manifest["publication"]["chapter_count"], 1)
            self.assertEqual(manifest["publication"]["chapters"][0]["page_count"], 5)
            self.assertEqual(manifest["expected"], 5)
            self.assertEqual(manifest["detected"], 5)
            self.assertIn("full", manifest["reading_mode"]["action"])
            self.assertEqual(manifest["selector"], "img.ts-main-image")
            self.assertEqual(manifest["saved"], 5)
            self.assertEqual(manifest["missing"], [])
            archive_path = Path(temp) / "document.cbz"
            self.assertTrue(archive_path.is_file())
            self.assertFalse((Path(temp) / "images").exists())
            self.assertFalse((Path(temp) / ".komaforge-work").exists())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [f"page-{index:04d}.png" for index in range(1, 6)],
                )
            self.assertEqual(manifest["output_format"], "cbz")
            self.assertEqual(manifest["artifact"]["path"], "document.cbz")

    def test_default_output_uses_title_for_folder_and_archive(self):
        from document_extractor.cli import parse_args

        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            args = parse_args([url])
            args.output_root = Path(temp)
            args.output = Path(temp) / "technical-placeholder"

            result = run(args)

            self.assertEqual(result, 0)
            output = Path(temp) / "Lecteur-test"
            archive = output / "Lecteur-test.cbz"
            manifest = json.loads(
                (output / "pages.json").read_text(encoding="utf-8")
            )
            self.assertTrue(archive.is_file())
            self.assertEqual(manifest["publication"]["title"], "Lecteur test")
            self.assertEqual(manifest["artifact"]["path"], "Lecteur-test.cbz")
            self.assertFalse((Path(temp) / "technical-placeholder").exists())

    def test_reader_without_loading_text_waits_for_delayed_images(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/delayed-image-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--inspect",
                    "--scope",
                    "document",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = result.stdout + result.stderr
            self.assertIn("Initialisation du lecteur", output)
            self.assertIn("Ressources de page trouvées : 3", output)
            self.assertIn("Pages attendues : 3", output)

    def test_paginated_reader_collects_each_replaced_image_in_order(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/paginated-image-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "original",
                    "--scope",
                    "document",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "Détection : manifeste du lecteur ChapterReader", result.stdout
            )
            self.assertIn("Ressources de page trouvées : 4", result.stdout)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["detected"], 4)
            self.assertEqual(manifest["saved"], 4)
            self.assertEqual(manifest["output_format"], "cbz")
            self.assertEqual(
                [Path(item["url"]).name for item in manifest["pages"]],
                ["page-1.png", "page-2.png", "page-3.png", "page-4.png"],
            )
            self.assertFalse((Path(temp) / "images").exists())
            archive_path = Path(temp) / "document.cbz"
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                    "page-0001.png",
                    "page-0002.png",
                    "page-0003.png",
                    "page-0004.png",
                    ],
                )

    def test_cta_images_alone_are_never_accepted_as_pages(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/cta-only-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--inspect",
                    "--scope",
                    "document",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("aucun groupe fiable de pages", result.stderr)
            self.assertFalse((Path(temp) / "pages.json").exists())

    def test_virtual_blob_reader_preserves_all_original_webp_pages(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/virtual-blob-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "original",
                    "--scope",
                    "document",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "Lecteur virtualisé : 7 page(s) originale(s) sur 3 écran(s)",
                result.stdout,
            )
            self.assertIn(
                "Détection : lecteur virtualisé à pages Blob", result.stdout
            )
            manifest_path = Path(temp) / "pages.json"
            raw_manifest = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(raw_manifest)
            self.assertNotIn("_embedded_", raw_manifest)
            self.assertEqual(manifest["detected"], 7)
            self.assertEqual(manifest["expected"], 7)
            self.assertEqual(manifest["saved"], 7)
            archive_path = Path(temp) / "document.cbz"
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [f"page-{index:04d}.webp" for index in range(1, 8)],
                )

    def test_canvas_reader_rejects_logos_and_reports_accessible_pages(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/canvas-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--inspect",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            output = result.stdout + result.stderr
            self.assertIn("Lecteur canvas/PDF détecté", output)
            self.assertIn("39 emplacement(s) accessible(s)", output)
            self.assertIn("captures basse qualité", output)
            self.assertFalse((Path(temp) / "pages.json").exists())
            self.assertFalse((Path(temp) / "images").exists())

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_canvas_reader_preserves_loaded_pdf_resource(self):
        import pikepdf

        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/network-pdf-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "pdf",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ressource PDF chargée par le navigateur", result.stdout)
            self.assertIn("Pages du PDF : 3", result.stdout)
            artifact = Path(temp) / "document.pdf"
            self.assertTrue(artifact.is_file())
            with pikepdf.Pdf.open(artifact) as document:
                self.assertEqual(len(document.pages), 3)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["detected"], 3)
            self.assertEqual(manifest["selector"], "network:application/pdf")
            self.assertEqual(manifest["resource_unit"], "pdf_document")
            self.assertFalse((Path(temp) / "images").exists())

    @unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "pypdfium2 absent")
    def test_network_pdf_can_be_converted_to_cbz_when_selected(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/network-pdf-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "cbz",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with zipfile.ZipFile(Path(temp) / "document.cbz") as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["page-0001.png", "page-0002.png", "page-0003.png"],
                )
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["output_format"], "cbz")
            self.assertEqual(manifest["resource_unit"], "rendered_pdf_page")
            self.assertEqual(manifest["render_dpi"], 200)
            self.assertFalse((Path(temp) / ".komaforge-work").exists())

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_network_pdf_is_not_declared_complete_when_metadata_announces_more(self):
        project = Path(__file__).resolve().parents[1]
        url = (
            f"http://127.0.0.1:{self.server.server_port}"
            "/network-pdf-reader-incomplete"
        )
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "pdf",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("[INCOMPLET] Publication : 3/10 pages", result.stdout)
            self.assertIn("Aucun PDF sauvegardé", result.stdout)
            self.assertFalse((Path(temp) / "document.partial.pdf").exists())
            self.assertFalse((Path(temp) / "document.pdf").exists())
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["expected"], 10)
            self.assertEqual(manifest["detected"], 3)
            self.assertEqual(manifest["saved"], 0)
            self.assertEqual(manifest["missing_count"], 7)
            self.assertEqual(manifest["missing"], ["4-10"])
            self.assertIn("pdf_diagnostics", manifest)
            trees = manifest["pdf_diagnostics"]["detached_ordered_page_trees"]
            self.assertEqual(len(trees), 1)
            self.assertEqual(trees[0]["declared_count"], 10)
            self.assertEqual(trees[0]["visible_prefix_matches"], 3)
            self.assertTrue(trees[0]["is_visible_prefix"])
            self.assertEqual(trees[0]["continuation_count"], 7)
            self.assertEqual(trees[0]["continuation_with_content"], 7)
            self.assertEqual(trees[0]["continuation_with_resources"], 7)
            self.assertIn(
                "3 pages visibles correspondent au préfixe", result.stdout
            )
            self.assertEqual(manifest["publication"]["status"], "incomplete")
            self.assertEqual(
                manifest["publication"]["chapters"][0]["status"], "incomplete"
            )

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_detached_page_tree_inspector_is_independent_and_read_only(self):
        diagnostics = inspect_detached_page_trees(DETACHED_TREE_PDF)
        self.assertEqual(diagnostics["visible_page_count"], 3)
        trees = diagnostics["detached_ordered_page_trees"]
        self.assertEqual(len(trees), 1)
        self.assertEqual(trees[0]["declared_count"], 10)
        self.assertEqual(trees[0]["resolved_page_count"], 10)
        self.assertTrue(trees[0]["count_matches_resolved"])
        self.assertEqual(trees[0]["visible_prefix_matches"], 3)
        self.assertEqual(trees[0]["continuation_count"], 7)
        self.assertTrue(trees[0]["is_structurally_complete"])

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_detached_page_tree_recovery_creates_a_valid_complete_pdf(self):
        import pikepdf
        from io import BytesIO

        recovered, details = recover_detached_page_tree(DETACHED_TREE_PDF, 10)
        self.assertEqual(details["source_visible_page_count"], 3)
        self.assertEqual(details["recovered_page_count"], 10)
        self.assertEqual(details["continuation_page_count"], 7)
        with pikepdf.Pdf.open(BytesIO(recovered)) as document:
            self.assertEqual(len(document.pages), 10)
            self.assertEqual(document.Root.Pages.get("/Count"), 10)

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_network_pdf_recovery_requires_explicit_authorized_option(self):
        import pikepdf

        project = Path(__file__).resolve().parents[1]
        url = (
            f"http://127.0.0.1:{self.server.server_port}"
            "/network-pdf-reader-incomplete"
        )
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "pdf",
                    "--recover-detached-pdf",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("[RÉCUPÉRÉ]", result.stdout)
            artifact = Path(temp) / "document.pdf"
            self.assertTrue(artifact.is_file())
            with pikepdf.Pdf.open(artifact) as document:
                self.assertEqual(len(document.pages), 10)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["detected"], 10)
            self.assertEqual(manifest["saved"], 10)
            self.assertEqual(manifest["missing_count"], 0)
            self.assertEqual(manifest["source_visible_page_count"], 3)
            self.assertTrue(manifest["recovered_from_detached_tree"])
            self.assertEqual(manifest["publication"]["status"], "complete")

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_interactive_original_mode_keeps_pdf_and_requests_recovery(self):
        import pikepdf

        project = Path(__file__).resolve().parents[1]
        url = (
            f"http://127.0.0.1:{self.server.server_port}"
            "/network-pdf-reader-incomplete"
        )
        with tempfile.TemporaryDirectory() as temp:
            from document_extractor.cli import parse_args

            args = parse_args([url, "--output", temp])
            args.interactive = True
            args.output_format = "original"
            with patch("builtins.input", return_value="oui") as prompt:
                result = run(args)

            self.assertEqual(result, 0)
            prompt.assert_called_once()
            artifact = Path(temp) / "document.pdf"
            self.assertTrue(artifact.is_file())
            with pikepdf.Pdf.open(artifact) as document:
                self.assertEqual(len(document.pages), 10)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["output_format"], "pdf")
            self.assertTrue(manifest["recovered_from_detached_tree"])

    def test_interactive_original_mode_selects_cbz_for_source_images(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            from document_extractor.cli import parse_args

            args = parse_args([url, "--output", temp])
            args.interactive = True
            args.output_format = "original"
            result = run(args)

            self.assertEqual(result, 0)
            self.assertTrue((Path(temp) / "document.cbz").is_file())
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["output_format"], "cbz")

    def test_network_epub_is_preserved_as_the_original_document(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/network-epub-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "original",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ressource EPUB chargée par le navigateur", result.stdout)
            artifact = Path(temp) / "document.epub"
            self.assertEqual(artifact.read_bytes(), NETWORK_EPUB)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["output_format"], "epub")
            self.assertEqual(manifest["resource_unit"], "epub_document")
            self.assertEqual(manifest["epub_spine_items"], 2)

    def test_incomplete_network_epub_is_reported_and_not_saved(self):
        project = Path(__file__).resolve().parents[1]
        url = (
            f"http://127.0.0.1:{self.server.server_port}"
            "/network-epub-reader-incomplete"
        )
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "original",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("[INCOMPLET] EPUB", result.stdout)
            self.assertIn("1 document(s) de lecture", result.stdout)
            self.assertFalse((Path(temp) / "document.epub").exists())
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["publication"]["status"], "incomplete")
            self.assertEqual(manifest["missing_count"], 1)
            self.assertEqual(
                manifest["epub_diagnostics"]["missing_referenced_documents"],
                ["OEBPS/three.xhtml"],
            )

    def test_incomplete_epub_inspection_is_explicitly_cancelled(self):
        project = Path(__file__).resolve().parents[1]
        url = (
            f"http://127.0.0.1:{self.server.server_port}"
            "/network-epub-reader-incomplete"
        )
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--inspect",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "[ANNULÉ] Extraction refusée : 2/3 document(s) disponible(s), "
                "1 manquant(s).",
                result.stdout,
            )
            self.assertIn("[ANNULÉ] Inspection incomplète", result.stdout)
            self.assertFalse((Path(temp) / "document.epub").exists())

    @unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
    def test_network_epub_can_be_converted_to_pdf_when_selected(self):
        import pikepdf

        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/network-epub-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "pdf",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = Path(temp) / "document.pdf"
            with pikepdf.Pdf.open(artifact) as document:
                self.assertGreaterEqual(len(document.pages), 2)
            manifest = json.loads((Path(temp) / "pages.json").read_text("utf-8"))
            self.assertEqual(manifest["output_format"], "pdf")
            self.assertEqual(manifest["resource_unit"], "epub_document")

    @unittest.skipUnless(
        importlib.util.find_spec("pikepdf")
        and importlib.util.find_spec("pypdfium2"),
        "pikepdf/pypdfium2 absents",
    )
    def test_network_epub_can_be_rendered_as_images_without_work_files(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/network-epub-reader"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--format",
                    "images",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            images = sorted((Path(temp) / "images").glob("page-*.png"))
            self.assertGreaterEqual(len(images), 2)
            self.assertFalse((Path(temp) / ".komaforge-work").exists())

    def test_inspection_detects_a_work_without_downloading(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/work"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--inspect",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Chapitres détectés : 3", result.stdout)
            self.assertIn("1. Chapitre 1", result.stdout)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_work_download_creates_one_valid_archive_per_selected_chapter(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/work"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--chapters",
                    "1-2",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            root = Path(temp)
            manifest = json.loads(
                (root / "publication.json").read_text(encoding="utf-8")
            )
            publication = manifest["publication"]
            self.assertEqual(publication["type"], "work")
            self.assertEqual(publication["chapter_count"], 3)
            self.assertEqual(publication["selected_chapter_count"], 2)
            self.assertEqual(publication["status"], "complete")
            self.assertEqual(
                [chapter["status"] for chapter in publication["chapters"]],
                ["complete", "complete"],
            )
            archives = sorted((root / "chapters").glob("*.cbz"))
            self.assertEqual(
                [archive.name for archive in archives],
                ["001-Chapitre-1.cbz", "002-Chapitre-2.cbz"],
            )
            for archive_path in archives:
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(
                        archive.namelist(),
                        ["page-0001.png", "page-0002.png"],
                    )
            self.assertFalse((root / ".komaforge-work").exists())

    def test_select_menu_creates_one_image_folder_per_selected_volume(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/select-work"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--chapters",
                    "1-2",
                    "--format",
                    "images",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Volumes détectés : 3", result.stdout)
            root = Path(temp)
            manifest = json.loads(
                (root / "publication.json").read_text(encoding="utf-8")
            )
            publication = manifest["publication"]
            self.assertEqual(publication["type"], "collection")
            self.assertEqual(publication["part_kind"], "volume")
            self.assertEqual(publication["part_count"], 3)
            self.assertEqual(publication["selected_part_count"], 2)
            self.assertEqual(
                [part["detected"] for part in publication["chapters"]],
                [3, 2],
            )
            self.assertEqual(
                [part["expected"] for part in publication["chapters"]],
                [3, 2],
            )
            self.assertEqual(
                [path.name for path in sorted((root / "volumes").iterdir())],
                ["001-Volume-1", "002-Volume-2"],
            )
            self.assertEqual(
                len(list((root / "volumes" / "001-Volume-1").glob("page-*.png"))),
                3,
            )
            self.assertEqual(
                len(list((root / "volumes" / "002-Volume-2").glob("page-*.png"))),
                2,
            )

    def test_direct_chapter_url_does_not_expand_to_the_whole_work(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/series/demo/chapter-2"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            root = Path(temp)
            self.assertTrue((root / "pages.json").is_file())
            self.assertTrue((root / "document.cbz").is_file())
            self.assertFalse((root / "publication.json").exists())

    def test_wrong_expected_count_stops_before_download(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/document"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--expected",
                    "6",
                    "--output",
                    temp,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((Path(temp) / "pages.json").exists())
            self.assertFalse((Path(temp) / "images").exists())
            work_images = Path(temp) / ".komaforge-work" / "images"
            self.assertFalse(work_images.exists())

    def test_svgz_detection_and_targeted_watermark_removal(self):
        project = Path(__file__).resolve().parents[1]
        url = f"http://127.0.0.1:{self.server.server_port}/svg-document"
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "document_extractor",
                    url,
                    "--output",
                    temp,
                    "--format",
                    "images",
                    "--watermarks",
                    "remove",
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = Path(temp)
            pages = sorted((output / "images").glob("page-*.svg"))
            self.assertEqual(len(pages), 2)
            for page in pages:
                data = page.read_bytes()
                self.assertNotIn(b"SPECIMEN", data)
                self.assertIn(b"Page de test", data)
            manifest = json.loads((output / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["watermark_policy"], "remove")
            self.assertEqual(
                [page["watermarks_removed"] for page in manifest["pages"]],
                [1, 1],
            )
            self.assertIn("non compressé", manifest["pages"][0]["normalization"])
            self.assertEqual(manifest["pages"][1]["normalization"], "gzip vers svg")


if __name__ == "__main__":
    unittest.main()
