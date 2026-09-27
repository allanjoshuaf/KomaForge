"""Reconstructible SQLite index built exclusively from KomaForge manifests."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .application import resolve_source
from .legacy_bridge import normalize_legacy_manifest
from .models import Part, Publication, Resource, Work
from .paths import canonical_source_identity


SCHEMA_VERSION = 1
MANIFEST_NAMES = {"pages.json", "publication.json"}


@dataclass(frozen=True, slots=True)
class RebuildSummary:
    manifests: int
    duplicate_manifests: int
    works: int
    publications: int
    parts: int
    resources: int


@dataclass(frozen=True, slots=True)
class _PublicationCandidate:
    work: Work
    publication: Publication
    manifest_path: Path
    created_at: str | None
    artifact_integrity: str
    artifact_integrity_rank: int


def discover_manifests(output_root: Path) -> tuple[Path, ...]:
    root = output_root.expanduser().resolve()
    if not root.is_dir():
        return ()
    manifests = [
        path
        for path in root.rglob("*.json")
        if path.name in MANIFEST_NAMES and ".komaforge-work" not in path.parts
    ]
    return tuple(sorted(manifests, key=lambda path: str(path).casefold()))


def _coverage_values(item) -> tuple[str | None, int | None, int | None, str | None]:
    coverage = item.coverage
    if coverage is None:
        return None, None, None, None
    return (
        coverage.status.value,
        coverage.available,
        coverage.expected,
        coverage.unit,
    )


def _safe_source_url(value: str) -> str:
    """Remove session-scoped query values before an URL reaches SQLite."""

    canonical = canonical_source_identity(value)
    if not canonical:
        raise ValueError("publication source URL cannot be empty")
    return canonical


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _open_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect(path)
    try:
        yield connection
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE works (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL
        );

        CREATE TABLE publications (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            manifest_path TEXT NOT NULL UNIQUE,
            created_at TEXT,
            artifact_integrity TEXT NOT NULL,
            legacy_status TEXT,
            coverage_status TEXT,
            coverage_available INTEGER,
            coverage_expected INTEGER,
            coverage_unit TEXT
        );

        CREATE TABLE parts (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            number TEXT,
            source_url TEXT NOT NULL,
            legacy_status TEXT,
            coverage_status TEXT,
            coverage_available INTEGER,
            coverage_expected INTEGER,
            coverage_unit TEXT,
            UNIQUE(publication_id, position)
        );

        CREATE TABLE resources (
            id TEXT PRIMARY KEY,
            part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            locator TEXT,
            filename TEXT,
            sha256 TEXT,
            sensitive_locator INTEGER NOT NULL DEFAULT 0,
            UNIQUE(part_id, position)
        );

        CREATE INDEX publications_source_id_idx ON publications(source_id);
        CREATE INDEX parts_publication_id_idx ON parts(publication_id);
        CREATE INDEX resources_part_id_idx ON resources(part_id);
        """
    )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _insert_resource(
    connection: sqlite3.Connection,
    part: Part,
    resource: Resource,
) -> None:
    public = resource.to_manifest()
    connection.execute(
        """
        INSERT INTO resources(
            id, part_id, kind, position, locator, filename, sha256,
            sensitive_locator
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resource.id,
            part.id,
            resource.kind.value,
            resource.position,
            public["locator"],
            resource.filename,
            resource.sha256,
            int(resource.sensitive_locator),
        ),
    )


def _insert_part(
    connection: sqlite3.Connection,
    publication: Publication,
    part: Part,
) -> int:
    status, available, expected, unit = _coverage_values(part)
    connection.execute(
        """
        INSERT INTO parts(
            id, publication_id, title, kind, position, number, source_url,
            legacy_status, coverage_status, coverage_available,
            coverage_expected, coverage_unit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            part.id,
            publication.id,
            part.title,
            part.kind.value,
            part.position,
            part.number,
            _safe_source_url(part.source_url),
            part.metadata.get("legacy_status"),
            status,
            available,
            expected,
            unit,
        ),
    )
    for resource in part.resources:
        _insert_resource(connection, part, resource)
    return len(part.resources)


def _insert_publication(
    connection: sqlite3.Connection,
    candidate: _PublicationCandidate,
) -> tuple[int, int]:
    work = candidate.work
    publication = candidate.publication
    status, available, expected, unit = _coverage_values(publication)
    connection.execute(
        """
        INSERT INTO publications(
            id, work_id, source_id, title, source_url, manifest_path,
            created_at, artifact_integrity, legacy_status, coverage_status,
            coverage_available, coverage_expected, coverage_unit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            publication.id,
            work.id,
            publication.source_id,
            publication.title,
            _safe_source_url(publication.source_url),
            str(candidate.manifest_path),
            candidate.created_at,
            candidate.artifact_integrity,
            publication.metadata.get("legacy_status"),
            status,
            available,
            expected,
            unit,
        ),
    )
    resources = sum(
        _insert_part(connection, publication, part)
        for part in publication.parts
    )
    return len(publication.parts), resources


def _read_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid KomaForge manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid KomaForge manifest {path}: root must be an object")
    return payload


def _artifact_records(payload: dict) -> tuple[dict, ...]:
    artifacts: list[dict] = []
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        artifacts.append(artifact)
    publication = payload.get("publication")
    if isinstance(publication, dict):
        for record in publication.get("chapters") or ():
            if isinstance(record, dict) and isinstance(record.get("artifact"), dict):
                artifacts.append(record["artifact"])
    return tuple(artifacts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_integrity(manifest_path: Path, payload: dict) -> tuple[str, int]:
    artifacts = _artifact_records(payload)
    if not artifacts:
        return "not_declared", 1
    all_hashed = True
    for artifact in artifacts:
        raw_path = artifact.get("path") or artifact.get("file")
        if not raw_path:
            return "invalid", 0
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = manifest_path.parent / path
        if not path.is_file():
            return "missing", 0
        expected = str(artifact.get("sha256") or "").strip()
        if not expected:
            all_hashed = False
            continue
        if _sha256(path).casefold() != expected.casefold():
            return "mismatch", 0
    if all_hashed:
        return "verified", 3
    return "present", 2


def _status_rank(candidate: _PublicationCandidate) -> int:
    status = str(candidate.publication.metadata.get("legacy_status") or "")
    return {
        "complete": 4,
        "limited_by_source": 3,
        "incomplete": 2,
        "": 1,
        "error": 0,
    }.get(status, 1)


def _created_at_rank(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OSError):
        return float("-inf")


def _candidate_sort_key(candidate: _PublicationCandidate) -> tuple:
    return (
        -_status_rank(candidate),
        -candidate.artifact_integrity_rank,
        -_created_at_rank(candidate.created_at),
        str(candidate.manifest_path).casefold(),
    )


def _load_candidates(
    manifests: tuple[Path, ...],
) -> tuple[tuple[_PublicationCandidate, ...], int]:
    by_publication: dict[str, list[_PublicationCandidate]] = {}
    for manifest_path in manifests:
        payload = _read_manifest(manifest_path)
        source_url = str(payload.get("source_url") or "")
        route = resolve_source(source_url)
        work = normalize_legacy_manifest(
            payload,
            route.adapter.id,
            title_hint=manifest_path.parent.name,
        )
        integrity, integrity_rank = _artifact_integrity(manifest_path, payload)
        created_at_value = payload.get("created_at")
        created_at = str(created_at_value) if created_at_value else None
        for publication in work.publications:
            candidate = _PublicationCandidate(
                work=work,
                publication=publication,
                manifest_path=manifest_path,
                created_at=created_at,
                artifact_integrity=integrity,
                artifact_integrity_rank=integrity_rank,
            )
            by_publication.setdefault(publication.id, []).append(candidate)

    selected = tuple(
        min(candidates, key=_candidate_sort_key)
        for _, candidates in sorted(by_publication.items())
    )
    duplicate_count = sum(len(candidates) - 1 for candidates in by_publication.values())
    return selected, duplicate_count


class LibraryIndex:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def rebuild(self, output_root: Path) -> RebuildSummary:
        """Atomically replace the index only after every manifest validates."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f"{self.path.stem}-",
            suffix=".sqlite.tmp",
            dir=self.path.parent,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        works_seen: set[str] = set()
        publication_count = 0
        part_count = 0
        resource_count = 0
        manifests = discover_manifests(output_root)
        try:
            candidates, duplicate_count = _load_candidates(manifests)
            with _open_connection(temporary) as connection:
                _create_schema(connection)
                for candidate in candidates:
                    work = candidate.work
                    if work.id not in works_seen:
                        connection.execute(
                            "INSERT INTO works(id, title) VALUES(?, ?)",
                            (work.id, work.title),
                        )
                        works_seen.add(work.id)
                    parts, resources = _insert_publication(connection, candidate)
                    publication_count += 1
                    part_count += parts
                    resource_count += resources
                connection.commit()
            os.replace(temporary, self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return RebuildSummary(
            manifests=len(manifests),
            duplicate_manifests=duplicate_count,
            works=len(works_seen),
            publications=publication_count,
            parts=part_count,
            resources=resource_count,
        )

    def schema_version(self) -> int:
        if not self.path.is_file():
            return 0
        with _open_connection(self.path) as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"]) if row else 0

    def list_works(self) -> tuple[dict, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT
                    works.id,
                    works.title,
                    COUNT(DISTINCT publications.id) AS publication_count,
                    COUNT(DISTINCT parts.id) AS part_count
                FROM works
                LEFT JOIN publications ON publications.work_id = works.id
                LEFT JOIN parts ON parts.publication_id = publications.id
                GROUP BY works.id, works.title
                ORDER BY works.title COLLATE NOCASE, works.id
                """
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def search_works(self, query: str) -> tuple[dict, ...]:
        value = str(query or "").strip()
        if not value:
            raise ValueError("library search query cannot be empty")
        if not self.path.is_file():
            return ()
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT
                    works.id,
                    works.title,
                    COUNT(DISTINCT publications.id) AS publication_count,
                    COUNT(DISTINCT parts.id) AS part_count
                FROM works
                LEFT JOIN publications ON publications.work_id = works.id
                LEFT JOIN parts ON parts.publication_id = publications.id
                WHERE works.title LIKE ? ESCAPE '\\' COLLATE NOCASE
                GROUP BY works.id, works.title
                ORDER BY works.title COLLATE NOCASE, works.id
                """,
                (pattern,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def iter_publications(self) -> Iterator[dict]:
        if not self.path.is_file():
            return
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM publications
                ORDER BY title COLLATE NOCASE, id
                """
            ).fetchall()
        for row in rows:
            yield dict(row)

    def list_publications(self) -> tuple[dict, ...]:
        """Return the stable public view without internal manifest paths."""

        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT
                    id, work_id, source_id, title, source_url, created_at,
                    artifact_integrity, legacy_status, coverage_status,
                    coverage_available, coverage_expected, coverage_unit
                FROM publications
                ORDER BY title COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def status(self) -> dict:
        if not self.path.is_file():
            return {
                "works": 0,
                "publications": 0,
                "parts": 0,
                "resources": 0,
                "artifact_integrity": {},
                "coverage": {},
                "legacy_status": {},
            }
        with _open_connection(self.path) as connection:
            counts = {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in ("works", "publications", "parts", "resources")
            }

            def grouped(column: str) -> dict:
                rows = connection.execute(
                    f"""
                    SELECT COALESCE({column}, 'unknown') AS value, COUNT(*) AS count
                    FROM publications
                    GROUP BY COALESCE({column}, 'unknown')
                    ORDER BY value
                    """
                ).fetchall()
                return {row["value"]: int(row["count"]) for row in rows}

            return {
                **counts,
                "artifact_integrity": grouped("artifact_integrity"),
                "coverage": grouped("coverage_status"),
                "legacy_status": grouped("legacy_status"),
            }

    def load_publication(self, publication_id: str) -> Publication | None:
        if not self.path.is_file():
            return None
        with _open_connection(self.path) as connection:
            row = connection.execute(
                """
                SELECT source_id, manifest_path
                FROM publications
                WHERE id = ?
                """,
                (publication_id,),
            ).fetchone()
        if row is None:
            return None
        manifest_path = Path(row["manifest_path"])
        payload = _read_manifest(manifest_path)
        work = normalize_legacy_manifest(
            payload,
            row["source_id"],
            title_hint=manifest_path.parent.name,
        )
        return next(
            (
                publication
                for publication in work.publications
                if publication.id == publication_id
            ),
            None,
        )

    def resource_locators(self) -> tuple[str | None, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT locator FROM resources ORDER BY part_id, position"
            ).fetchall()
        return tuple(row["locator"] for row in rows)

    def source_urls(self) -> tuple[str, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT source_url FROM publications
                UNION ALL
                SELECT source_url FROM parts
                ORDER BY source_url
                """
            ).fetchall()
        return tuple(row["source_url"] for row in rows)
