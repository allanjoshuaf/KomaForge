from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_extractor.cli import (
    build_parser,
    interactive_setup,
    normalize_url_input,
    parse_args,
)
from document_extractor.paths import default_output_dir, safe_slug


class PortablePathTests(unittest.TestCase):
    def test_version_is_available_without_a_url(self):
        with self.assertRaises(SystemExit) as exit_context:
            with patch("sys.stdout") as stdout:
                build_parser().parse_args(["--version"])
        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("komaforge 0.3.1", stdout.write.call_args.args[0])

    def test_slug_is_portable(self):
        self.assertEqual(safe_slug("Page spéciale / 185"), "Page-sp-ciale-185")

    def test_output_is_under_configured_application_home(self):
        with tempfile.TemporaryDirectory() as temp:
            result = default_output_dir(
                "https://votre-site.example/document/42", Path(temp)
            )
            self.assertEqual(
                result,
                (Path(temp) / "extractions" / "votre-site.example-42").resolve(),
            )

    @unittest.skipUnless(os.name == "nt", "chemin propre a Windows")
    def test_direct_cli_uses_the_system_drive_on_windows(self):
        with patch.dict(os.environ, {"SystemDrive": "C:"}):
            args = parse_args(["https://example.test/book/7"])
            self.assertEqual(
                args.output,
                Path(r"C:\Extractions\Manga\example.test-7"),
            )

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
