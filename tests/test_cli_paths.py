from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from document_extractor.cli import (
    build_parser,
    interactive_setup,
    normalize_url_input,
    parse_args,
)
from document_extractor.paths import (
    canonical_source_identity,
    choose_title_output_dir,
    default_output_dir,
    default_profile_dir,
    ensure_output_dir_is_compatible,
    publication_folder_title,
    safe_slug,
)
from document_extractor.terminal_ui import (
    BRAND_ART,
    BRAND_ART_COLORS,
    BRAND_FRAME_DELAY,
    BRAND_FRAMES,
    MESSAGES,
    RUNTIME_MESSAGES,
    TerminalUI,
    display_width,
    normalize_language,
)
from document_extractor.engine import cleanup_temporary_profile


class PortablePathTests(unittest.TestCase):
    def test_version_is_available_without_a_url(self):
        with self.assertRaises(SystemExit) as exit_context:
            with patch("sys.stdout") as stdout:
                build_parser().parse_args(["--version"])
        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("komaforge 0.4.0", stdout.write.call_args.args[0])

    def test_slug_is_portable(self):
        self.assertEqual(safe_slug("Page spéciale / 185"), "Page-speciale-185")
        self.assertEqual(
            safe_slug("Attack on Titan - Chapter 1"),
            "Attack-on-Titan-Chapter-1",
        )

    def test_opaque_reader_url_uses_book_title_and_chapter(self):
        url = (
            "https://www.mangareader.pro/reader/1?"
            "url=https%3A%2F%2Fmangakatana.com%2Fmanga%2Fattack-on-titan%2Fc12"
            "&title=Attack%20on%20Titan"
        )
        title = publication_folder_title("Chapter 12 | MangaReader", url)
        self.assertEqual(title, "Attack on Titan - Chapter 12")

    def test_reader_branding_is_removed_from_detected_book_title(self):
        title = publication_folder_title(
            "The Demon Star - eBooks.com Reader (Preview)",
            "https://reader.ebooks.com/preview?bid=347114076&hash=temporary",
        )
        self.assertEqual(title, "The Demon Star")

    def test_manga_up_branding_is_removed_from_detected_title(self):
        title = publication_folder_title(
            "Fullmetal Alchemist | Manga UP!",
            "https://global.manga-up.com/manga/126",
        )
        self.assertEqual(title, "Fullmetal Alchemist")

    def test_title_directory_never_reuses_another_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "Same-Title"
            first.mkdir()
            (first / "pages.json").write_text(
                json.dumps({"source_url": "https://example.test/book/one"}),
                encoding="utf-8",
            )
            selected = choose_title_output_dir(
                root,
                "Same Title",
                "https://example.test/book/two",
            )
            self.assertEqual(selected, root / "Same-Title-2")

    def test_title_directory_reuses_the_same_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "Same-Title"
            existing.mkdir()
            (existing / "pages.json").write_text(
                json.dumps({"source_url": "https://example.test/book/one"}),
                encoding="utf-8",
            )
            selected = choose_title_output_dir(
                root,
                "Same Title",
                "https://example.test/book/one",
            )
            self.assertEqual(selected, existing)

    def test_work_output_does_not_mix_with_older_single_document_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "Fullmetal-Alchemist"
            existing.mkdir()
            (existing / "pages.json").write_text(
                json.dumps(
                    {
                        "source_url": (
                            "https://global.manga-up.com/manga/126"
                            "?utm_source=animeplanet"
                        )
                    }
                ),
                encoding="utf-8",
            )

            selected = choose_title_output_dir(
                root,
                "Fullmetal Alchemist",
                "https://global.manga-up.com/manga/126?utm_source=animeplanet",
                expected_manifest="publication.json",
            )

            self.assertEqual(selected, root / "Fullmetal-Alchemist-2")

    def test_explicit_output_rejects_another_book(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "pages.json").write_text(
                json.dumps({"source_url": "https://example.test/book/one"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "autre ouvrage"):
                ensure_output_dir_is_compatible(
                    output,
                    "https://example.test/book/two",
                )

    def test_ebook_identity_ignores_expiring_session_parameters(self):
        first = (
            "https://reader.ebooks.com/preview?uid=first&reqid=1&"
            "bid=347114076&t=10&hash=old"
        )
        second = (
            "https://reader.ebooks.com/preview?uid=second&reqid=2&"
            "bid=347114076&t=20&hash=new"
        )
        self.assertEqual(
            canonical_source_identity(first),
            canonical_source_identity(second),
        )

    def test_output_is_under_configured_application_home(self):
        with tempfile.TemporaryDirectory() as temp:
            result = default_output_dir(
                "https://votre-site.example/document/42", Path(temp)
            )
            self.assertEqual(
                result,
                (Path(temp) / "extractions" / "votre-site.example-42").resolve(),
            )

    def test_browser_profile_uses_local_application_data(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp}, clear=False):
                with patch("document_extractor.paths.os.name", "nt"):
                    self.assertEqual(
                        default_profile_dir(),
                        (Path(temp) / "KomaForge" / "ChromeProfile").resolve(),
                    )

    @unittest.skipUnless(os.name == "nt", "chemin propre a Windows")
    def test_direct_cli_uses_the_system_drive_on_windows(self):
        with patch.dict(os.environ, {"SystemDrive": "C:"}):
            args = parse_args(["https://example.test/book/7"])
            self.assertEqual(
                args.output,
                Path(r"C:\Extractions\Manga\example.test-7"),
            )
            self.assertTrue(args.output_auto_named)
            self.assertEqual(args.output_root, Path(r"C:\Extractions\Manga"))

    def test_source_has_no_hard_coded_windows_profile(self):
        source_root = Path(__file__).resolve().parents[1] / "src"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in source_root.rglob("*.py")
        )
        self.assertNotRegex(source, r"(?i)C:\\Users\\[^\\\r\n\"']+")

    def test_repository_does_not_publish_private_identity_or_tooling(self):
        project = Path(__file__).resolve().parents[1]
        forbidden = tuple(
            value.casefold()
            for value in (
                "al" + "lan",
                "jo" + "shua",
                "co" + "dex",
                "chat" + "gpt",
                "open" + "ai",
            )
        )
        if not (project / ".git").is_dir():
            self.skipTest("copie sans métadonnées Git")
        tracked = subprocess.check_output(
            ["git", "ls-files"],
            cwd=project,
            text=True,
            encoding="utf-8",
        ).splitlines()
        public_files = [project / relative for relative in tracked]
        for path in public_files:
            content = path.read_text(encoding="utf-8", errors="ignore").casefold()
            for value in forbidden:
                self.assertNotIn(value, content, str(path.relative_to(project)))

    def test_cli_keeps_original_options_only(self):
        parser = build_parser()
        options = {
            option
            for action in parser._actions
            for option in action.option_strings
            if option not in {"-h", "--help"}
        }
        self.assertEqual(
            options,
            {
                "--version",
                "--language",
                "--lang",
                "--selector",
                "--expected",
                "--output",
                "--inspect",
                "--scope",
                "--chapters",
                "--allow-host",
                "--reading-mode-selector",
                "--reading-mode-value",
                "--ready-selector",
                "--wait-for-user",
                "--profile-dir",
                "--chrome",
                "--retries",
                "--workers",
                "--max-image-mb",
                "--watermarks",
                "--watermark-text",
                "--format",
                "--pdf",
                "--recover-detached-pdf",
            },
        )

    def test_detached_pdf_recovery_can_feed_another_output_format(self):
        args = parse_args(
            [
                "https://example.test/book/7",
                "--format",
                "cbz",
                "--recover-detached-pdf",
            ]
        )
        self.assertEqual(args.output_format, "cbz")
        self.assertTrue(args.recover_detached_pdf)

    def test_browser_opening_keeps_original_cdp_method(self):
        engine = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "document_extractor"
            / "engine.py"
        ).read_text(encoding="utf-8")
        self.assertIn("subprocess.Popen", engine)
        self.assertIn("connect_over_cdp", engine)
        self.assertNotIn("launch_persistent_context", engine)

    def test_beginner_menu_accepts_url_and_keeps_the_format_choice(self):
        args = build_parser().parse_args([])
        answers = iter(
            [
                "1",
                "1",
                "https://example.test/document/9",
                "",
                "",
                "",
            ]
        )
        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            configured = interactive_setup(args)
        self.assertEqual(configured.url, "https://example.test/document/9")
        self.assertIsNone(configured.selector)
        self.assertIsNone(configured.expected)
        self.assertFalse(configured.pdf)
        self.assertEqual(configured.output_format, "original")
        self.assertFalse(configured.wait_for_user)
        self.assertEqual(configured.watermarks, "remove")
        self.assertTrue(configured.interactive)
        self.assertEqual(configured.chapters, "ask")
        self.assertEqual(configured.language, "fr")

    def test_four_interface_languages_have_the_complete_menu_catalog(self):
        required = set(MESSAGES["fr"])
        for language in ("fr", "en", "ru", "zh"):
            self.assertEqual(set(MESSAGES[language]), required)
            stream = StringIO()
            TerminalUI(language, stream=stream).header()
            rendered = stream.getvalue()
            self.assertIn("KomaForge", rendered)
            self.assertIn(MESSAGES[language]["tagline"], rendered)
            box = [
                line for line in rendered.splitlines()
                if line.startswith(("╭", "│", "╰"))
            ]
            self.assertEqual(len(box), 3)
            self.assertEqual(len({display_width(line) for line in box}), 1)
            self.assertTrue(box[1].endswith("│"))

    def test_brand_mascot_is_compact_and_survives_without_color(self):
        self.assertEqual(len(BRAND_ART), 11)
        self.assertEqual(len(BRAND_ART_COLORS), len(BRAND_ART))
        self.assertLessEqual(max(map(len, BRAND_ART)), 60)
        self.assertEqual(len(BRAND_FRAMES), 5)
        self.assertTrue(all(len(frame) == len(BRAND_ART) for frame in BRAND_FRAMES))

        stream = StringIO()
        TerminalUI("fr", stream=stream).header()
        rendered = stream.getvalue()
        self.assertNotIn("\033[", rendered)
        for line in BRAND_ART:
            self.assertIn(line, rendered)

    def test_brand_animation_is_short_and_tty_only(self):
        class TTYStream(StringIO):
            def isatty(self):
                return True

        stream = TTYStream()
        environment = {
            "TERM": "xterm-256color",
            "NO_COLOR": "",
            "CI": "",
            "KOMAFORGE_NO_ANIMATION": "",
            "KOMAFORGE_REDUCE_MOTION": "",
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch("document_extractor.terminal_ui.time.sleep") as sleep,
        ):
            TerminalUI("fr", stream=stream).header()

        rendered = stream.getvalue()
        self.assertIn("\033[?25l", rendered)
        self.assertIn("\033[?25h", rendered)
        self.assertIn(f"\033[{len(BRAND_ART)}A", rendered)
        self.assertEqual(sleep.call_count, 4)
        sleep.assert_called_with(BRAND_FRAME_DELAY)

        reduced_stream = TTYStream()
        with (
            patch.dict(
                os.environ,
                {**environment, "KOMAFORGE_REDUCE_MOTION": "1"},
                clear=False,
            ),
            patch("document_extractor.terminal_ui.time.sleep") as reduced_sleep,
        ):
            TerminalUI("fr", stream=reduced_stream).header()
        self.assertNotIn("\033[?25l", reduced_stream.getvalue())
        reduced_sleep.assert_not_called()

    def test_language_aliases_are_normalized(self):
        self.assertEqual(normalize_language("Français"), "fr")
        self.assertEqual(normalize_language("English"), "en")
        self.assertEqual(normalize_language("Русский"), "ru")
        self.assertEqual(normalize_language("中文"), "zh")

    def test_runtime_messages_cover_every_interface_language(self):
        for translations in RUNTIME_MESSAGES.values():
            self.assertEqual(set(translations), {"fr", "en", "ru", "zh"})

    def test_temporary_chrome_profile_is_removed(self):
        temporary = tempfile.TemporaryDirectory(prefix="komaforge-profile-test-")
        profile = Path(temporary.name)
        (profile / "nested").mkdir()
        (profile / "nested" / "state.txt").write_text("test", encoding="utf-8")

        self.assertTrue(cleanup_temporary_profile(temporary, profile))
        self.assertFalse(profile.exists())

    def test_direct_cli_selects_one_output_format(self):
        args = parse_args(["https://example.test/book/7", "--format", "epub"])
        self.assertEqual(args.output_format, "epub")

    def test_markdown_link_is_reduced_to_its_plain_url(self):
        url = "https://example.test/book/7"
        self.assertEqual(normalize_url_input(f"[{url}]({url})"), url)

    def test_mismatched_markdown_link_is_rejected(self):
        with self.assertRaises(SystemExit):
            normalize_url_input(
                "[https://visible.example/](https://different.example/)"
            )

    def test_historical_pdf_alias_maps_to_pdf_format(self):
        args = parse_args(["https://example.test/book/7", "--pdf"])
        self.assertEqual(args.output_format, "pdf")


if __name__ == "__main__":
    unittest.main()
