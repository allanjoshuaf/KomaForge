"""Persistent user state kept independent from the reconstructible library index."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


STATE_SCHEMA_VERSION = 2


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


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str
    created_at: str


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    row = connection.execute(
        "SELECT value FROM state_metadata WHERE key = 'schema_version'"
    ).fetchone()
    version = int(row["value"]) if row is not None else 0
    if version not in {0, 1, STATE_SCHEMA_VERSION}:
        raise RuntimeError(f"unsupported library state schema version {version}")
    connection.executescript(
        """
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

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS publication_categories (
            publication_id TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            PRIMARY KEY(publication_id, category_id),
            FOREIGN KEY(publication_id)
                REFERENCES tracked_publications(publication_id)
                ON DELETE CASCADE,
            FOREIGN KEY(category_id)
                REFERENCES categories(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS publication_categories_category_idx
        ON publication_categories(category_id, publication_id);
        """
    )
    if version == 0:
        connection.execute(
            "INSERT INTO state_metadata(key, value) VALUES('schema_version', ?)",
            (str(STATE_SCHEMA_VERSION),),
        )
    elif version == 1:
        connection.execute(
            "UPDATE state_metadata SET value = ? WHERE key = 'schema_version'",
            (str(STATE_SCHEMA_VERSION),),
        )


def _category_name(value: str) -> tuple[str, str]:
    name = " ".join(str(value or "").split())
    if not name:
        raise ValueError("category name cannot be empty")
    if len(name) > 80:
        raise ValueError("category name cannot exceed 80 characters")
    if any(ord(character) < 32 for character in name):
        raise ValueError("category name cannot contain control characters")
    return name, name.casefold()


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

    def create_category(self, name: str) -> Category:
        display_name, name_key = _category_name(name)
        self._prepare()
        with _open_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO categories(name, name_key, created_at)
                VALUES(?, ?, ?)
                ON CONFLICT(name_key) DO NOTHING
                """,
                (display_name, name_key, _now()),
            )
            row = connection.execute(
                "SELECT id, name, created_at FROM categories WHERE name_key = ?",
                (name_key,),
            ).fetchone()
            connection.commit()
        return Category(int(row["id"]), row["name"], row["created_at"])

    def categories(self) -> tuple[Category, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            rows = connection.execute(
                "SELECT id, name, created_at FROM categories ORDER BY name_key, id"
            ).fetchall()
            connection.commit()
        return tuple(
            Category(int(row["id"]), row["name"], row["created_at"])
            for row in rows
        )

    def delete_category(self, name: str) -> bool:
        _, name_key = _category_name(name)
        if not self.path.is_file():
            return False
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            cursor = connection.execute(
                "DELETE FROM categories WHERE name_key = ?", (name_key,)
            )
            connection.commit()
        return cursor.rowcount == 1

    def assign_category(self, publication_id: str, name: str) -> Category:
        tracked = {item.publication_id for item in self.tracked()}
        if publication_id not in tracked:
            raise ValueError("publication must be tracked before assigning a category")
        category = self.create_category(name)
        with _open_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO publication_categories(publication_id, category_id)
                VALUES(?, ?)
                ON CONFLICT(publication_id, category_id) DO NOTHING
                """,
                (publication_id, category.id),
            )
            connection.commit()
        return category

    def remove_category(self, publication_id: str, name: str) -> bool:
        _, name_key = _category_name(name)
        if not self.path.is_file():
            return False
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            cursor = connection.execute(
                """
                DELETE FROM publication_categories
                WHERE publication_id = ?
                  AND category_id = (
                    SELECT id FROM categories WHERE name_key = ?
                  )
                """,
                (publication_id, name_key),
            )
            connection.commit()
        return cursor.rowcount == 1

    def category_members(self, name: str) -> tuple[str, ...]:
        _, name_key = _category_name(name)
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            exists = connection.execute(
                "SELECT 1 FROM categories WHERE name_key = ?", (name_key,)
            ).fetchone()
            if exists is None:
                raise KeyError(name)
            rows = connection.execute(
                """
                SELECT publication_categories.publication_id
                FROM publication_categories
                JOIN categories ON categories.id = publication_categories.category_id
                WHERE categories.name_key = ?
                ORDER BY publication_categories.publication_id
                """,
                (name_key,),
            ).fetchall()
            connection.commit()
        return tuple(row["publication_id"] for row in rows)

    def publication_categories(self, publication_id: str) -> tuple[Category, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            rows = connection.execute(
                """
                SELECT categories.id, categories.name, categories.created_at
                FROM categories
                JOIN publication_categories
                  ON publication_categories.category_id = categories.id
                WHERE publication_categories.publication_id = ?
                ORDER BY categories.name_key, categories.id
                """,
                (publication_id,),
            ).fetchall()
            connection.commit()
        return tuple(
            Category(int(row["id"]), row["name"], row["created_at"])
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
