"""Lanceur portable : `python extract.py`."""

from __future__ import annotations

import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
os.environ.setdefault("DOCUMENT_EXTRACTOR_HOME", str(HERE))

from document_extractor.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
