from __future__ import annotations

import hashlib
import html
import posixpath
import shutil
import struct
import subprocess
import tempfile
import time
import zipfile
from io import BytesIO
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from defusedxml import ElementTree


OUTPUT_FORMATS = ("original", "cbz", "cbr", "pdf", "epub", "images")
PDF_IMAGE_DPI = (96, 96)


def inspect_epub(data: bytes) -> dict:
    """Valide un EPUB et retourne son paquet ainsi que son ordre de lecture."""
    try:
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            names = set(archive.namelist())
            if "mimetype" not in names or archive.read("mimetype").strip() != b"application/epub+zip":
                raise ValueError("mimetype EPUB absent ou invalide")
            if "META-INF/container.xml" not in names:
                raise ValueError("META-INF/container.xml absent")
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise ValueError("chemin du paquet OPF absent")
            package_path = posixpath.normpath(rootfile.get("full-path"))
            if package_path.startswith("../") or package_path not in names:
                raise ValueError("paquet OPF introuvable")
            package = ElementTree.fromstring(archive.read(package_path))
            package_dir = posixpath.dirname(package_path)
            manifest = {
                item.get("id"): item
                for item in package.findall(".//{*}manifest/{*}item")
                if item.get("id")
            }
            spine_paths: list[str] = []
            for itemref in package.findall(".//{*}spine/{*}itemref"):
                item = manifest.get(itemref.get("idref"))
                if item is None or item.get("media-type") != "application/xhtml+xml":
                    continue
                href = unquote(item.get("href") or "")
                path = posixpath.normpath(posixpath.join(package_dir, href))
                if path.startswith("../") or path not in names:
                    raise ValueError(f"section EPUB introuvable : {href}")
                spine_paths.append(path)
            if not spine_paths:
                raise ValueError("ordre de lecture EPUB vide")
            referenced_documents: set[str] = set()
            navigation_paths = [
                path
                for path, item in (
                    (
                        posixpath.normpath(
                            posixpath.join(package_dir, unquote(entry.get("href") or ""))
                        ),
                        entry,
                    )
                    for entry in manifest.values()
                )
                if item.get("media-type") == "application/xhtml+xml"
                and (
                    "nav" in (item.get("properties") or "").split()
                    or "toc" in (item.get("id") or "").casefold()
                    or "toc" in posixpath.basename(path).casefold()
                )
                and path in names
            ]
            for navigation_path in navigation_paths:
                navigation = ElementTree.fromstring(archive.read(navigation_path))
                navigation_dir = posixpath.dirname(navigation_path)
                for element in navigation.iter():
                    href = unquote(element.get("href") or "").strip()
                    parsed = urlparse(href)
                    if not href or parsed.scheme or parsed.netloc:
                        continue
                    document_path = posixpath.normpath(
                        posixpath.join(navigation_dir, parsed.path)
                    )
                    if document_path.lower().endswith((".xhtml", ".html", ".htm")):
                        referenced_documents.add(document_path)

            local_entries: list[str] = []
            position = 0
            while True:
                position = data.find(b"PK\x03\x04", position)
                if position < 0 or position + 30 > len(data):
                    break
                fields = struct.unpack_from("<IHHHHHIIIHH", data, position)
                name_length, extra_length = fields[-2], fields[-1]
                name_start = position + 30
                name_end = name_start + name_length
                local_entries.append(
                    data[name_start:name_end].decode("utf-8", errors="replace")
                )
                position = name_end + extra_length

            end_offset = data.rfind(b"PK\x05\x06")
            trailing_bytes = None
            if end_offset >= 0 and end_offset + 22 <= len(data):
                comment_length = struct.unpack_from("<H", data, end_offset + 20)[0]
                trailing_bytes = max(
                    len(data) - (end_offset + 22 + comment_length), 0
                )
            missing_references = sorted(referenced_documents - names)
            present_references = sorted(referenced_documents & names)
            orphan_local_entries = sorted(set(local_entries) - names)
            title_node = package.find(".//{http://purl.org/dc/elements/1.1/}title")
            return {
                "package_path": package_path,
                "spine_paths": spine_paths,
                "spine_item_count": len(spine_paths),
                "title": (title_node.text or "").strip() if title_node is not None else "",
                "entry_count": len(names),
                "referenced_document_count": len(referenced_documents),
                "present_referenced_documents": present_references,
                "missing_referenced_documents": missing_references,
                "orphan_local_entries": orphan_local_entries,
                "local_entry_count": len(local_entries),
                "trailing_bytes_after_eocd": trailing_bytes,
                "is_structurally_complete": not missing_references,
            }
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ValueError(f"EPUB invalide : {exc}") from exc


def _extract_epub_safely(data: bytes, target: Path) -> dict:
    info = inspect_epub(data)
    target.mkdir(parents=True, exist_ok=True)
    target_root = target.resolve()
    with zipfile.ZipFile(BytesIO(data), "r") as archive:
        for member in archive.infolist():
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Chemin EPUB dangereux : {member.filename}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError(f"Lien symbolique refusé dans l'EPUB : {member.filename}")
            destination = target.joinpath(*relative.parts).resolve()
            if destination != target_root and target_root not in destination.parents:
                raise RuntimeError(f"Chemin EPUB hors dossier : {member.filename}")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    return info


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_target(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _replace_atomic(partial: Path, final: Path) -> None:
    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError(f"Sortie temporaire invalide : {partial}")
    partial.replace(final)


def create_cbz(files: list[Path], output_path: Path) -> Path:
    """Crée un CBZ sans transformer les images, puis vérifie chaque octet."""
    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)
        with zipfile.ZipFile(partial, "r") as archive:
            names = archive.namelist()
            if names != [path.name for path in files]:
                raise RuntimeError("L'ordre des pages du CBZ est invalide.")
            for path in files:
                if hashlib.sha256(archive.read(path.name)).hexdigest() != file_sha256(path):
                    raise RuntimeError(f"Le CBZ a altéré {path.name}.")
        _replace_atomic(partial, output_path)
        return output_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def find_rar_executable() -> Path | None:
    discovered = shutil.which("rar") or shutil.which("rar.exe")
    if discovered:
        return Path(discovered)
    candidates = (
        Path(r"C:\Program Files\WinRAR\Rar.exe"),
        Path(r"C:\Program Files (x86)\WinRAR\Rar.exe"),
    )
    return next((path for path in candidates if path.is_file()), None)


def create_cbr(files: list[Path], output_path: Path) -> Path:
    """Crée un vrai conteneur RAR/CBR en mode stockage et vérifie son extraction."""
    rar = find_rar_executable()
    if rar is None:
        raise RuntimeError(
            "Le format CBR demande l'outil `rar` (WinRAR). "
            "Installez WinRAR ou choisissez CBZ, qui ne demande aucun outil externe."
        )
    partial = output_path.with_name(f"{output_path.stem}.part{output_path.suffix}")
    partial.unlink(missing_ok=True)
    try:
        command = [
            str(rar),
            "a",
            "-ep1",
            "-m0",
            "-idq",
            "-y",
            str(partial),
            *(str(path) for path in files),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not partial.is_file():
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Échec de création CBR : {details or result.returncode}")

        with tempfile.TemporaryDirectory(prefix="komaforge-cbr-check-") as temp:
            check_dir = Path(temp)
            verify = subprocess.run(
                [str(rar), "x", "-inul", "-o+", "-y", str(partial), str(check_dir) + "\\"],
                capture_output=True,
                check=False,
            )
            if verify.returncode != 0:
                raise RuntimeError("Le CBR créé ne peut pas être relu.")
            extracted = sorted(path for path in check_dir.iterdir() if path.is_file())
            if [path.name for path in extracted] != sorted(path.name for path in files):
                raise RuntimeError("Le contenu du CBR est incomplet.")
            originals = {path.name: file_sha256(path) for path in files}
            for path in extracted:
                if file_sha256(path) != originals[path.name]:
                    raise RuntimeError(f"Le CBR a altéré {path.name}.")
        _replace_atomic(partial, output_path)
        return output_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _bitmap_pdf_bytes(files: list[Path], img2pdf) -> bytes:
    """Fixe seulement l'échelle PDF; les pixels source ne sont pas rééchantillonnés."""
    layout = img2pdf.get_fixed_dpi_layout_fun(PDF_IMAGE_DPI)
    return img2pdf.convert(
        [str(path) for path in files],
        layout_fun=layout,
    )


def create_pdf(
    files: list[Path],
    output_path: Path,
    chrome_executable: Path | None = None,
) -> Path:
    """Encapsule les images sans redimensionnement et conserve les SVG en vectoriel."""
    try:
        import img2pdf
    except ImportError as exc:
        raise RuntimeError(
            "Le format PDF demande img2pdf : `python -m pip install -e \".[pdf]\"`."
        ) from exc

    svg_present = any(path.suffix.lower() == ".svg" for path in files)
    if svg_present:
        return _create_mixed_pdf(files, output_path, img2pdf, chrome_executable)

    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    try:
        partial.write_bytes(_bitmap_pdf_bytes(files, img2pdf))
        if not partial.read_bytes()[:5] == b"%PDF-":
            raise RuntimeError("Le PDF produit est invalide.")
        _replace_atomic(partial, output_path)
        return output_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def find_chrome_executable() -> Path | None:
    discovered = shutil.which("chrome") or shutil.which("chrome.exe")
    if discovered:
        return Path(discovered)
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _render_svg_pdf_with_chrome(
    chrome: Path,
    source: Path,
    page_pdf: Path,
    profile_dir: Path,
) -> None:
    result = subprocess.run(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--no-pdf-header-footer",
            "--no-first-run",
            f"--user-data-dir={profile_dir}",
            f"--print-to-pdf={page_pdf}",
            source.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    deadline = time.time() + 10
    while time.time() < deadline and not page_pdf.is_file():
        time.sleep(0.1)
    if (
        result.returncode != 0
        or not page_pdf.is_file()
        or page_pdf.stat().st_size == 0
        or page_pdf.read_bytes()[:5] != b"%PDF-"
    ):
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"Échec du rendu Chrome de {source.name} : "
            f"{details or result.returncode}"
        )


def create_pdf_from_epub_bytes(
    data: bytes,
    output_path: Path,
    chrome_executable: Path,
) -> tuple[Path, dict]:
    """Imprime chaque section XHTML d'un EPUB avec Chrome puis fusionne le PDF."""
    if not chrome_executable.is_file():
        raise RuntimeError(f"Chrome introuvable : {chrome_executable}")
    try:
        import pikepdf
    except ImportError as exc:
        raise RuntimeError(
            "La conversion EPUB vers PDF demande pikepdf : "
            "`python -m pip install -e \".[pdf]\"`."
        ) from exc

    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="komaforge-epub-render-") as temp:
            root = Path(temp)
            source_root = root / "source"
            info = _extract_epub_safely(data, source_root)
            page_pdfs: list[Path] = []
            for index, relative in enumerate(info["spine_paths"], start=1):
                source = source_root.joinpath(*PurePosixPath(relative).parts)
                page_pdf = root / f"section-{index:04d}.pdf"
                _render_svg_pdf_with_chrome(
                    chrome_executable,
                    source,
                    page_pdf,
                    root / f"chrome-profile-{index:04d}",
                )
                page_pdfs.append(page_pdf)

            output = pikepdf.Pdf.new()
            sources = []
            try:
                for page_pdf in page_pdfs:
                    source_pdf = pikepdf.Pdf.open(page_pdf)
                    sources.append(source_pdf)
                    output.pages.extend(source_pdf.pages)
                output.save(partial)
            finally:
                for source_pdf in sources:
                    source_pdf.close()
                output.close()

        with pikepdf.Pdf.open(partial) as verification:
            page_count = len(verification.pages)
            if page_count < 1:
                raise RuntimeError("La conversion EPUB n'a produit aucune page PDF.")
        _replace_atomic(partial, output_path)
        return output_path, {**info, "page_count": page_count}
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def render_pdf_bytes_to_images(
    data: bytes,
    output_dir: Path,
    dpi: int = 200,
) -> list[Path]:
    """Rasterise toutes les pages d'un PDF en PNG sans perte supplémentaire."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError(
            "La conversion d'un document vers CBZ, CBR, EPUB fixe ou images "
            "demande pypdfium2 : `python -m pip install -e \".[conversion]\"`."
        ) from exc
    if dpi < 72:
        raise ValueError("La résolution de rendu PDF doit être d'au moins 72 ppp.")

    output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(data)
    files: list[Path] = []
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = None
            try:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil()
                output = output_dir / f"page-{index + 1:04d}.png"
                image.save(output, format="PNG", optimize=False)
                if output.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError(f"Rendu PNG invalide : {output.name}")
                files.append(output)
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
    finally:
        document.close()
    if not files:
        raise RuntimeError("Le PDF à convertir ne contient aucune page.")
    return files


def _create_mixed_pdf(
    files: list[Path],
    output_path: Path,
    img2pdf,
    chrome_executable: Path | None,
) -> Path:
    chrome = chrome_executable or find_chrome_executable()
    if chrome is None or not chrome.is_file():
        raise RuntimeError(
            "Le PDF contient des pages SVG et demande Google Chrome pour les rendre "
            "fidèlement."
        )
    try:
        import pikepdf
    except ImportError as exc:
        raise RuntimeError(
            "Le PDF SVG demande pikepdf : `python -m pip install -e \".[pdf]\"`."
        ) from exc

    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="komaforge-pdf-pages-") as temp:
            temp_dir = Path(temp)
            page_pdfs: list[Path] = []
            for index, source in enumerate(files, start=1):
                page_pdf = temp_dir / f"page-{index:04d}.pdf"
                if source.suffix.lower() == ".svg":
                    _render_svg_pdf_with_chrome(
                        chrome,
                        source,
                        page_pdf,
                        temp_dir / f"chrome-profile-{index:04d}",
                    )
                else:
                    page_pdf.write_bytes(_bitmap_pdf_bytes([source], img2pdf))
                page_pdfs.append(page_pdf)

            output = pikepdf.Pdf.new()
            sources = []
            try:
                for page_pdf in page_pdfs:
                    source_pdf = pikepdf.Pdf.open(page_pdf)
                    sources.append(source_pdf)
                    output.pages.extend(source_pdf.pages)
                output.save(partial)
            finally:
                for source_pdf in sources:
                    source_pdf.close()
                output.close()

        with pikepdf.Pdf.open(partial) as verification:
            if len(verification.pages) != len(files):
                raise RuntimeError("Le PDF final ne contient pas toutes les pages.")
        _replace_atomic(partial, output_path)
        return output_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


def create_epub(files: list[Path], output_path: Path, title: str) -> Path:
    """Crée un EPUB 3 à mise en page fixe en conservant les images originales."""
    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    escaped_title = html.escape(title)
    book_id = hashlib.sha256(
        "".join(file_sha256(path) for path in files).encode("ascii")
    ).hexdigest()

    manifest_images: list[str] = []
    manifest_pages: list[str] = []
    spine: list[str] = []
    nav_links: list[str] = []

    try:
        with zipfile.ZipFile(partial, "w") as archive:
            archive.writestr(
                "mimetype",
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
""",
                compress_type=zipfile.ZIP_DEFLATED,
            )

            for index, path in enumerate(files, start=1):
                image_name = f"images/{path.name}"
                page_name = f"pages/page-{index:04d}.xhtml"
                image_id = f"image-{index}"
                page_id = f"page-{index}"
                archive.write(
                    path,
                    arcname=f"OEBPS/{image_name}",
                    compress_type=zipfile.ZIP_STORED,
                )
                archive.writestr(
                    f"OEBPS/{page_name}",
                    f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="fr">
<head><title>Page {index}</title><meta name="viewport" content="width=device-width,height=device-height"/></head>
<body style="margin:0;text-align:center;background:#000"><img src="../{html.escape(image_name)}" alt="Page {index}" style="max-width:100%;max-height:100vh"/></body>
</html>
""",
                    compress_type=zipfile.ZIP_DEFLATED,
                )
                manifest_images.append(
                    f'<item id="{image_id}" href="{html.escape(image_name)}" media-type="{_media_type(path)}"/>'
                )
                manifest_pages.append(
                    f'<item id="{page_id}" href="{page_name}" media-type="application/xhtml+xml"/>'
                )
                spine.append(f'<itemref idref="{page_id}"/>')
                nav_links.append(f'<li><a href="{page_name}">Page {index}</a></li>')

            archive.writestr(
                "OEBPS/nav.xhtml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="fr">
<head><title>{escaped_title}</title></head>
<body><nav epub:type="toc"><h1>{escaped_title}</h1><ol>{''.join(nav_links)}</ol></nav></body>
</html>
""",
                compress_type=zipfile.ZIP_DEFLATED,
            )
            archive.writestr(
                "OEBPS/content.opf",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:sha256:{book_id}</dc:identifier>
    <dc:title>{escaped_title}</dc:title><dc:language>fr</dc:language>
    <meta property="rendition:layout">pre-paginated</meta>
  </metadata>
  <manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>{''.join(manifest_images)}{''.join(manifest_pages)}</manifest>
  <spine page-progression-direction="ltr">{''.join(spine)}</spine>
</package>
""",
                compress_type=zipfile.ZIP_DEFLATED,
            )

        with zipfile.ZipFile(partial, "r") as archive:
            first = archive.infolist()[0]
            if first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED:
                raise RuntimeError("Structure EPUB invalide : mimetype incorrect.")
            for path in files:
                embedded = archive.read(f"OEBPS/images/{path.name}")
                if hashlib.sha256(embedded).hexdigest() != file_sha256(path):
                    raise RuntimeError(f"L'EPUB a altéré {path.name}.")
        _replace_atomic(partial, output_path)
        return output_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def create_selected_output(
    output_format: str,
    files: list[Path],
    output_dir: Path,
    title: str,
    chrome_executable: Path | None = None,
    output_stem: str = "document",
) -> Path:
    if not files:
        raise RuntimeError("Aucune page à exporter.")
    if output_format == "images":
        return files[0].parent
    if not output_stem or Path(output_stem).name != output_stem:
        raise ValueError("Nom de sortie invalide.")
    output_path = output_dir / f"{output_stem}.{output_format}"
    if output_format == "cbz":
        return create_cbz(files, output_path)
    if output_format == "cbr":
        return create_cbr(files, output_path)
    if output_format == "pdf":
        return create_pdf(files, output_path, chrome_executable)
    if output_format == "epub":
        return create_epub(files, output_path, title)
    raise ValueError(f"Format non pris en charge : {output_format}")


def remove_validated_work_directory(work_dir: Path, output_dir: Path) -> None:
    work_dir = work_dir.resolve()
    output_dir = output_dir.resolve()
    if work_dir.parent != output_dir or work_dir.name != ".komaforge-work":
        raise RuntimeError(f"Refus de supprimer un dossier de travail inattendu : {work_dir}")
    shutil.rmtree(work_dir)
