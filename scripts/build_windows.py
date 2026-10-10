"""Build the Windows portable distribution from an isolated environment."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from document_extractor import __version__


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("The portable Windows build must run on Windows.")
    bundle_name = f"KomaForge-{__version__}-windows-x64"
    dist = ROOT / "dist" / bundle_name
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
        "--name", "KomaForge", "--paths", str(ROOT / "src"),
        "--distpath", str(dist), "--workpath", str(ROOT / "build" / "portable"),
        "--specpath", str(ROOT / "build"),
        "--icon", str(ROOT / "assets" / "komaforge.ico"),
        "--collect-all", "playwright", "--collect-all", "pikepdf",
        "--collect-all", "pypdfium2", "--hidden-import", "img2pdf",
        "--hidden-import", "PIL.Image", "--add-data", f"{ROOT / 'assets'};assets",
        str(ROOT / "extract.py"),
    ], cwd=ROOT, check=True)
    package_portable(bundle_name)


def package_portable(bundle_name: str) -> None:
    dist = ROOT / "dist" / bundle_name
    app = dist / "KomaForge"
    if not (app / "KomaForge.exe").is_file():
        raise RuntimeError("Build KomaForge.exe before packaging")
    for name in ("LICENSE", "README.md", "CHANGELOG.md"):
        shutil.copy2(ROOT / name, app / name)
    shutil.copy2(ROOT / "scripts" / "Install-KomaForge.ps1", app)
    shutil.copy2(ROOT / "scripts" / "PORTABLE.md", app / "LISEZ-MOI.md")
    archive = Path(shutil.make_archive(str(ROOT / "dist" / bundle_name), "zip", dist))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = ROOT / "dist" / "SHA256SUMS.txt"
    checksums.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Portable archive: {archive.name}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
