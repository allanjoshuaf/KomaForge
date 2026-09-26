from __future__ import annotations

import hashlib
import importlib.util
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from document_extractor.formats import (
    create_cbr,
    create_cbz,
    create_epub,
    create_pdf,
    find_chrome_executable,
    inspect_epub,
    render_pdf_bytes_to_images,
    create_selected_output,
    remove_validated_work_directory,
)
from tests.mock_site import INCOMPLETE_EPUB, NETWORK_EPUB, NETWORK_PDF


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100adf64e3f0000000049454e44ae426082"
)
JPEG_MINIMAL = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "08" * 64
    + "ffc0000b080001000101011100ffc40014000100000000000000000000000000000000"
    + "ffda0008010100003f00ffd9"
)


def make_rgb_png(
    width: int,
    height: int,
    pixels_per_meter: int | None = None,
) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    rows = b"".join(b"\x00" + (b"\xff\xff\xff" * width) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    density = (
        chunk(b"pHYs", struct.pack(">IIB", pixels_per_meter, pixels_per_meter, 1))
        if pixels_per_meter
        else b""
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + density
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class OutputFormatTests(unittest.TestCase):
    def make_pages(self, root: Path) -> list[Path]:
        first = root / "page-0001.png"
        second = root / "page-0002.jpg"
        first.write_bytes(PNG_1X1)
        second.write_bytes(JPEG_MINIMAL)
        return [first, second]

    def test_cbz_preserves_original_bytes_and_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = self.make_pages(root)
            output = create_cbz(pages, root / "document.cbz")
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), [path.name for path in pages])
                for page in pages:
                    self.assertEqual(archive.read(page.name), page.read_bytes())

    def test_epub_preserves_original_image_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = self.make_pages(root)
            output = create_epub(pages, root / "document.epub", "Titre test")
            with zipfile.ZipFile(output) as archive:
                first = archive.infolist()[0]
                self.assertEqual(first.filename, "mimetype")
                self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
                for page in pages:
                    self.assertEqual(
                        archive.read(f"OEBPS/images/{page.name}"), page.read_bytes()
                    )

    def test_epub_inspection_reads_the_real_spine_order(self):
        info = inspect_epub(NETWORK_EPUB)
        self.assertEqual(info["spine_item_count"], 2)
        self.assertEqual(
            info["spine_paths"],
            ["OEBPS/one.xhtml", "OEBPS/two.xhtml"],
        )
        self.assertTrue(info["is_structurally_complete"])

    def test_epub_inspection_finds_documents_named_but_absent(self):
        info = inspect_epub(INCOMPLETE_EPUB)
        self.assertFalse(info["is_structurally_complete"])
        self.assertEqual(info["referenced_document_count"], 3)
        self.assertEqual(
            info["missing_referenced_documents"],
            ["OEBPS/three.xhtml"],
        )
        self.assertEqual(info["orphan_local_entries"], [])
        self.assertEqual(info["trailing_bytes_after_eocd"], 0)

    @unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "pypdfium2 absent")
    def test_pdf_rasterization_produces_one_lossless_png_per_page(self):
        with tempfile.TemporaryDirectory() as temp:
            files = render_pdf_bytes_to_images(NETWORK_PDF, Path(temp), dpi=96)
            self.assertEqual(len(files), 3)
            self.assertTrue(all(path.read_bytes().startswith(b"\x89PNG") for path in files))

    @unittest.skipUnless(importlib.util.find_spec("img2pdf"), "img2pdf non installé")
    def test_pdf_is_created_with_stable_pixel_based_page_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page = root / "page-0001.png"
            page.write_bytes(make_rgb_png(32, 32))
            output = create_pdf([page], root / "document.pdf")
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            self.assertGreater(output.stat().st_size, len(PNG_1X1))

    @unittest.skipUnless(
        importlib.util.find_spec("img2pdf") and importlib.util.find_spec("pikepdf"),
        "img2pdf/pikepdf absents",
    )
    def test_pdf_ignores_absurd_image_dpi_and_preserves_page_order(self):
        import pikepdf

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            short = root / "page-0001.png"
            tall = root / "page-0002.png"
            short.write_bytes(make_rgb_png(690, 200, pixels_per_meter=10_000_000))
            tall.write_bytes(make_rgb_png(900, 1500, pixels_per_meter=10_000_000))

            output = create_pdf([short, tall], root / "document.pdf")

            with pikepdf.Pdf.open(output) as pdf:
                self.assertEqual(len(pdf.pages), 2)
                sizes = [
                    (
                        float(page.MediaBox[2]) - float(page.MediaBox[0]),
                        float(page.MediaBox[3]) - float(page.MediaBox[1]),
                    )
                    for page in pdf.pages
                ]
            self.assertAlmostEqual(sizes[0][0], 690 * 0.75, places=2)
            self.assertAlmostEqual(sizes[0][1], 200 * 0.75, places=2)
            self.assertAlmostEqual(sizes[1][0], 900 * 0.75, places=2)
            self.assertAlmostEqual(sizes[1][1], 1500 * 0.75, places=2)

    @unittest.skipUnless(
        importlib.util.find_spec("img2pdf")
        and importlib.util.find_spec("pikepdf")
        and find_chrome_executable(),
        "Chrome/img2pdf/pikepdf indisponible",
    )
    def test_svg_pdf_keeps_a_vector_page(self):
        with tempfile.TemporaryDirectory() as temp:
            import pikepdf

            root = Path(temp)
            page = root / "page-0001.svg"
            page.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1600">'
                '<rect width="1200" height="1600" fill="white"/>'
                '<text x="100" y="200">Texte vectoriel</text></svg>',
                encoding="utf-8",
            )
            second = root / "page-0002.svg"
            second.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1600">'
                '<rect width="1200" height="1600" fill="white"/>'
                '<text x="100" y="300">Deuxième page</text></svg>',
                encoding="utf-8",
            )
            output = create_pdf([page, second], root / "document.pdf")
            with pikepdf.Pdf.open(output) as pdf:
                self.assertEqual(len(pdf.pages), 2)
                self.assertEqual([float(value) for value in pdf.pages[0].MediaBox], [0, 0, 648, 864])

    @unittest.skipUnless(
        importlib.util.find_spec("pypdfium2") and find_chrome_executable(),
        "Chrome/pypdfium2 indisponible",
    )
    def test_svg_cbz_contains_native_size_png_pages(self):
        from PIL import Image
        from io import BytesIO

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = []
            for index, color in enumerate(("#ff0000", "#0000ff"), start=1):
                page = root / f"page-{index:04d}.svg"
                page.write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1600">'
                    f'<rect width="1200" height="1600" fill="{color}"/>'
                    f'<text x="100" y="200">Page {index}</text></svg>',
                    encoding="utf-8",
                )
                pages.append(page)

            output = create_cbz(pages, root / "document.cbz", find_chrome_executable())

            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["page-0001.png", "page-0002.png"],
                )
                self.assertIsNone(archive.testzip())
                for name in archive.namelist():
                    data = archive.read(name)
                    self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                    with Image.open(BytesIO(data)) as image:
                        self.assertEqual(image.size, (1200, 1600))

    def test_no_inkscape_dependency_remains(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "document_extractor"
            / "formats.py"
        ).read_text(encoding="utf-8").lower()
        self.assertNotIn("inkscape", source)

    def test_images_output_returns_original_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = self.make_pages(root)
            result = create_selected_output("images", pages, root, "Test")
            self.assertEqual(result, root)
            self.assertEqual(hashlib.sha256(pages[0].read_bytes()).hexdigest(), hashlib.sha256(PNG_1X1).hexdigest())

    def test_selected_output_accepts_a_safe_chapter_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = self.make_pages(root)
            output = create_selected_output(
                "cbz",
                pages,
                root,
                "Chapitre 2",
                output_stem="002-chapitre-2",
            )
            self.assertEqual(output.name, "002-chapitre-2.cbz")

    def test_cbr_never_creates_a_fake_rar_when_rar_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pages = self.make_pages(root)
            with patch("document_extractor.formats.find_rar_executable", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "WinRAR"):
                    create_cbr(pages, root / "document.cbr")
            self.assertFalse((root / "document.cbr").exists())

    def test_work_cleanup_refuses_unexpected_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unexpected = root / "images"
            unexpected.mkdir()
            with self.assertRaisesRegex(RuntimeError, "Refus"):
                remove_validated_work_directory(unexpected, root)
            self.assertTrue(unexpected.is_dir())


if __name__ == "__main__":
    unittest.main()
