"""Inspect archive integrity and render sample pages for visual review."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageOps, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    thumbnails = []
    summary = {"artifact": args.artifact.name}
    if args.artifact.suffix.lower() == ".cbz":
        with zipfile.ZipFile(args.artifact) as archive:
            entries = sorted(name for name in archive.namelist() if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
            if not entries:
                raise ValueError("No raster page in the archive")
            selected = {0, 1, len(entries) // 2, len(entries) - 1}
            manifest_path = args.artifact.parent / "pages.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            expected_hashes = {item["file"]: item.get("sha256") for item in manifest.get("pages", [])}
            for index, entry in enumerate(entries):
                data = archive.read(entry)
                digest = hashlib.sha256(data).hexdigest()
                if expected_hashes.get(entry) and expected_hashes[entry] != digest:
                    raise ValueError(f"Checksum mismatch: {entry}")
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    if index in selected:
                        sample = image.convert("RGB")
                        sample.save(args.output / f"page-{index + 1:04d}.png")
                        thumbnails.append((index + 1, sample))
            summary.update(pages=len(entries), decoded=len(entries), checksums=len(expected_hashes))
    elif args.artifact.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(args.artifact)
        try:
            summary["pages"] = len(document)
            for index in sorted({0, min(1, len(document) - 1), len(document) // 2, len(document) - 1}):
                page = document[index]
                bitmap = page.render(scale=1)
                sample = bitmap.to_pil().convert("RGB")
                sample.save(args.output / f"page-{index + 1:04d}.png")
                thumbnails.append((index + 1, sample))
                bitmap.close()
                page.close()
        finally:
            document.close()
    else:
        raise SystemExit("Supported review formats: CBZ and PDF")
    sheet = Image.new("RGB", (440 * len(thumbnails), 660), "white")
    draw = ImageDraw.Draw(sheet)
    for slot, (number, sample) in enumerate(thumbnails):
        fitted = ImageOps.contain(sample, (420, 615))
        sheet.paste(fitted, (slot * 440 + (440 - fitted.width) // 2, 35))
        draw.text((slot * 440 + 12, 12), f"Page {number}", fill="black")
    sheet.save(args.output / "contact-sheet.png")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
