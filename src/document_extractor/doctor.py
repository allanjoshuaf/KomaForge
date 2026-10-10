"""Read-only local health checks for the KomaForge application layer."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from .jobs import QUEUE_SCHEMA_VERSION
from .library import SCHEMA_VERSION
from .library_state import STATE_SCHEMA_VERSION
from .source_packages import inspect_source_packages


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    id: str
    status: str
    summary: str
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"pass", "warn", "fail"}:
            raise ValueError("doctor status must be pass, warn, or fail")


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def status(self) -> str:
        if any(check.status == "fail" for check in self.checks):
            return "fail"
        if any(check.status == "warn" for check in self.checks):
            return "warn"
        return "pass"

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "counts": {
                status: sum(check.status == status for check in self.checks)
                for status in ("pass", "warn", "fail")
            },
            "checks": [asdict(check) for check in self.checks],
        }


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _directory_check(path: Path) -> DoctorCheck:
    if path.exists() and not path.is_dir():
        return DoctorCheck(
            "output-root",
            "fail",
            "output root is not a directory",
            str(path),
        )
    writable_parent = path if path.is_dir() else _nearest_existing_parent(path)
    if not writable_parent.is_dir() or not os.access(writable_parent, os.W_OK):
        return DoctorCheck(
            "output-root",
            "fail",
            "output root cannot be created or written",
            str(path),
        )
    return DoctorCheck(
        "output-root",
        "pass",
        "output root is ready" if path.is_dir() else "output root can be created",
        str(path),
    )


def _sqlite_schema_check(
    check_id: str,
    path: Path,
    table: str,
    expected: int,
    *,
    absent_summary: str,
    migratable: frozenset[int] = frozenset(),
) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck(check_id, "pass", absent_summary, str(path))
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            row = connection.execute(
                f"SELECT value FROM {table} WHERE key = 'schema_version'"
            ).fetchone()
        version = int(row[0]) if row else 0
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return DoctorCheck(check_id, "fail", "SQLite file is unreadable", str(exc))
    if version != expected:
        if version in migratable:
            return DoctorCheck(
                check_id,
                "warn",
                f"schema version {version} will migrate to {expected} when opened",
                str(path),
            )
        return DoctorCheck(
            check_id,
            "fail",
            f"incompatible schema version {version}; expected {expected}",
            str(path),
        )
    return DoctorCheck(
        check_id,
        "pass",
        f"schema version {version} is compatible",
        str(path),
    )


def run_doctor(
    *,
    root: Path,
    chrome: Path,
    sources_directory: Path,
) -> DoctorReport:
    """Inspect local prerequisites without creating or migrating application data."""

    resolved_root = root.expanduser().resolve()
    checks: list[DoctorCheck] = [
        DoctorCheck(
            "python",
            "pass" if sys.version_info >= (3, 10) else "fail",
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        DoctorCheck(
            "chrome",
            "pass" if chrome.expanduser().is_file() else "fail",
            "Chrome executable found"
            if chrome.expanduser().is_file()
            else "Chrome executable is missing",
            str(chrome.expanduser()),
        ),
        _directory_check(resolved_root),
    ]
    for module_name in ("playwright", "defusedxml"):
        installed = importlib.util.find_spec(module_name) is not None
        checks.append(
            DoctorCheck(
                f"dependency-{module_name}",
                "pass" if installed else "fail",
                f"required dependency {module_name} is "
                f"{'installed' if installed else 'missing'}",
            )
        )
    optional = {
        module_name: importlib.util.find_spec(module_name) is not None
        for module_name in ("img2pdf", "pikepdf", "pypdfium2")
    }
    checks.append(
        DoctorCheck(
            "optional-conversion",
            "pass",
            "optional conversion support inspected",
            ", ".join(
                f"{name}={'yes' if installed else 'no'}"
                for name, installed in optional.items()
            ),
        )
    )
    app_dir = resolved_root / ".komaforge"
    checks.extend(
        (
            _sqlite_schema_check(
                "library-index",
                app_dir / "library.sqlite",
                "metadata",
                SCHEMA_VERSION,
                absent_summary="library index is absent and reconstructible",
            ),
            _sqlite_schema_check(
                "library-state",
                app_dir / "state.sqlite",
                "state_metadata",
                STATE_SCHEMA_VERSION,
                absent_summary="library state is not initialized yet",
                migratable=frozenset({1, 2}),
            ),
            _sqlite_schema_check(
                "job-queue",
                app_dir / "jobs.sqlite",
                "queue_metadata",
                QUEUE_SCHEMA_VERSION,
                absent_summary="job queue is not initialized yet",
            ),
        )
    )
    packages = inspect_source_packages(sources_directory)
    invalid_packages = [item for item in packages if not item.valid]
    checks.append(
        DoctorCheck(
            "source-packages",
            "warn" if invalid_packages else "pass",
            (
                f"{len(packages) - len(invalid_packages)} valid and "
                f"{len(invalid_packages)} rejected source manifest(s)"
                if packages
                else "no third-party source manifest installed"
            ),
            "; ".join(
                f"{item.path.name}: {item.error}" for item in invalid_packages
            )
            or str(sources_directory.expanduser().resolve()),
        )
    )
    return DoctorReport(tuple(checks))
