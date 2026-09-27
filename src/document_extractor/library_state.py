"""Persistent user state kept independent from the reconstructible library index."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TrackedPublication:
    publication_id: str
    added_at: str


@dataclass(frozen=True, slots=True)
class ReadingProgress:
    publication_id: str
    part_id: str
    resource_position: int
    completed: bool
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
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
        CREATE TABLE IF NOT EXISTS state_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tracked_publications (
            publication_id TEXT PRIMARY KEY,
            added_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reading_progress (
            part_id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            resource_position INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(publication_id)
                REFERENCES tracked_publications(publication_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS reading_progress_publication_idx
        ON reading_progress(publication_id, completed);
        """
    )
    row = connection.execute(
        "SELECT value FROM state_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO state_metadata(key, value) VALUES('schema_version', ?)",
            (str(STATE_SCHEMA_VERSION),),
        )
    elif int(row["value"]) != STATE_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported library state schema version {row['value']}"
        )


class LibraryState:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            connection.commit()

    def track(self, publication_id: str) -> TrackedPublication:
        value = str(publication_id or "").strip()
        if not value:
            raise ValueError("publication_id cannot be empty")
        self._prepare()
        timestamp = _now()
        with _open_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO tracked_publications(publication_id, added_at)
                VALUES(?, ?)
                ON CONFLICT(publication_id) DO NOTHING
                """,
                (value, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM tracked_publications WHERE publication_id = ?",
                (value,),
            ).fetchone()
            connection.commit()
        return TrackedPublication(row["publication_id"], row["added_at"])

    def untrack(self, publication_id: str) -> bool:
        if not self.path.is_file():
            return False
        with _open_connection(self.path) as connection:
            cursor = connection.execute(
                "DELETE FROM tracked_publications WHERE publication_id = ?",
                (publication_id,),
            )
            connection.commit()
        return cursor.rowcount == 1

    def tracked(self) -> tuple[TrackedPublication, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            rows = connection.execute(
                "SELECT * FROM tracked_publications ORDER BY added_at, publication_id"
            ).fetchall()
        return tuple(
            TrackedPublication(row["publication_id"], row["added_at"])
            for row in rows
        )

    def set_progress(
        self,
        publication_id: str,
        part_id: str,
        resource_position: int,
        *,
        completed: bool = False,
    ) -> ReadingProgress:
        if not isinstance(resource_position, int) or isinstance(resource_position, bool):
            raise ValueError("resource_position must be an integer")
        if resource_position < 0:
            raise ValueError("resource_position cannot be negative")
        if not isinstance(completed, bool):
            raise ValueError("completed must be a boolean")
        tracked = {item.publication_id for item in self.tracked()}
        if publication_id not in tracked:
            raise ValueError("publication must be tracked before recording progress")
        timestamp = _now()
        with _open_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO reading_progress(
                    part_id, publication_id, resource_position, completed, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(part_id) DO UPDATE SET
                    publication_id = excluded.publication_id,
                    resource_position = excluded.resource_position,
                    completed = excluded.completed,
                    updated_at = excluded.updated_at
                """,
                (
                    part_id,
                    publication_id,
                    resource_position,
                    int(completed),
                    timestamp,
                ),
            )
            connection.commit()
        return ReadingProgress(
            publication_id,
            part_id,
            resource_position,
            completed,
            timestamp,
        )

    def progress(self, publication_id: str | None = None) -> tuple[ReadingProgress, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            if publication_id is None:
                rows = connection.execute(
                    "SELECT * FROM reading_progress ORDER BY updated_at, part_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM reading_progress
                    WHERE publication_id = ?
                    ORDER BY updated_at, part_id
                    """,
                    (publication_id,),
                ).fetchall()
        return tuple(
            ReadingProgress(
                publication_id=row["publication_id"],
                part_id=row["part_id"],
                resource_position=int(row["resource_position"]),
                completed=bool(row["completed"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        )
