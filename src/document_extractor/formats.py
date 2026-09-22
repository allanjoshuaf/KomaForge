from __future__ import annotations

import hashlib
import html
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


OUTPUT_FORMATS = ("cbz", "cbr", "pdf", "epub", "images")


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


def create_pdf(files: list[Path], output_path: Path) -> Path:
    """Encapsule les pages sans redimensionnement avec img2pdf."""
    try:
        import img2pdf
    except ImportError as exc:
        raise RuntimeError(
            "Le format PDF demande img2pdf : `python -m pip install -e \".[pdf]\"`."
        ) from exc

    partial = _atomic_target(output_path)
    partial.unlink(missing_ok=True)
    try:
        partial.write_bytes(img2pdf.convert([str(path) for path in files]))
        if not partial.read_bytes()[:5] == b"%PDF-":
            raise RuntimeError("Le PDF produit est invalide.")
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
) -> Path:
    if not files:
        raise RuntimeError("Aucune page à exporter.")
    if output_format == "images":
        return files[0].parent
    output_path = output_dir / f"document.{output_format}"
    if output_format == "cbz":
        return create_cbz(files, output_path)
    if output_format == "cbr":
        return create_cbr(files, output_path)
    if output_format == "pdf":
        return create_pdf(files, output_path)
    if output_format == "epub":
        return create_epub(files, output_path, title)
    raise ValueError(f"Format non pris en charge : {output_format}")


def remove_validated_work_directory(work_dir: Path, output_dir: Path) -> None:
    work_dir = work_dir.resolve()
    output_dir = output_dir.resolve()
    if work_dir.parent != output_dir or work_dir.name != ".komaforge-work":
        raise RuntimeError(f"Refus de supprimer un dossier de travail inattendu : {work_dir}")
    shutil.rmtree(work_dir)
