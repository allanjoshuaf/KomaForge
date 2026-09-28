"""Persistent application jobs kept separate from the reconstructible library."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Mapping
from urllib.parse import parse_qs, urlparse

from .application import resolve_source


QUEUE_SCHEMA_VERSION = 1
MAX_RUN_LIMIT = 1000


class JobAction(str, Enum):
    INSPECT = "inspect"
    DOWNLOAD = "download"
    UPDATE = "update"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def validate_run_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("limit must be an integer from 1 to 1000")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer from 1 to 1000") from exc
    if not 1 <= limit <= MAX_RUN_LIMIT:
        raise ValueError("limit must be an integer from 1 to 1000")
    return limit


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    action: JobAction
    source_id: str
    source_url: str
    status: JobStatus
    created_at: str
    updated_at: str
    attempts: int = 0
    options: Mapping[str, object] | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.source_id or not self.source_url:
            raise ValueError("job identity and source fields cannot be empty")
        if self.attempts < 0:
            raise ValueError("job attempts cannot be negative")
        if self.options is not None and not isinstance(self.options, Mapping):
            raise ValueError("job options must be a mapping")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_persistable_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("job source must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("job source URL cannot contain credentials")
    volatile = {"hash", "reqid", "session", "t", "token", "uid"}
    query_keys = {
        key.casefold().strip("_-")
        for key in parse_qs(parsed.query, keep_blank_values=True)
    }
    if volatile.intersection(query_keys):
        raise ValueError(
            "job source URL contains a temporary session parameter; "
            "use the stable publication URL"
        )
    route = resolve_source(value)
    if route.adapter.id == "ebooks" and parsed.hostname.casefold() == "reader.ebooks.com":
        raise ValueError(
            "eBooks reader sessions cannot be persisted; use the product URL"
        )
    return value


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
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
        CREATE TABLE IF NOT EXISTS queue_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            options_json TEXT NOT NULL,
            last_error TEXT
        );

        CREATE INDEX IF NOT EXISTS jobs_pending_idx
        ON jobs(status, created_at, id);
        """
    )
    row = connection.execute(
        "SELECT value FROM queue_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO queue_metadata(key, value) VALUES('schema_version', ?)",
            (str(QUEUE_SCHEMA_VERSION),),
        )
    elif int(row["value"]) != QUEUE_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported job queue schema version {row['value']}"
        )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        action=JobAction(row["action"]),
        source_id=row["source_id"],
        source_url=row["source_url"],
        status=JobStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        attempts=int(row["attempts"]),
        options=json.loads(row["options_json"]),
        last_error=row["last_error"],
    )


class JobQueue:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            connection.commit()

    def enqueue(
        self,
        action: JobAction,
        source_url: str,
        *,
        options: Mapping[str, object] | None = None,
    ) -> Job:
        if not isinstance(action, JobAction):
            raise ValueError("action must be a JobAction")
        stable_url = _validate_persistable_url(source_url)
        route = resolve_source(stable_url)
        option_values = dict(options or {})
        try:
            options_json = json.dumps(
                option_values,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("job options must be JSON serializable") from exc
        self._prepare()
        timestamp = _now()
        job_id = str(uuid.uuid4())
        with _open_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, action, source_id, source_url, status, created_at,
                    updated_at, attempts, options_json, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, NULL)
                """,
                (
                    job_id,
                    action.value,
                    route.adapter.id,
                    stable_url,
                    JobStatus.PENDING.value,
                    timestamp,
                    timestamp,
                    options_json,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _row_to_job(row)

    def list(self, status: JobStatus | None = None) -> tuple[Job, ...]:
        if not self.path.is_file():
            return ()
        with _open_connection(self.path) as connection:
            _create_schema(connection)
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at, id"
                ).fetchall()
            else:
                if not isinstance(status, JobStatus):
                    raise ValueError("status must be a JobStatus or None")
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at, id",
                    (status.value,),
                ).fetchall()
        return tuple(_row_to_job(row) for row in rows)

    def claim_next(
        self,
        actions: tuple[JobAction, ...] | None = None,
    ) -> Job | None:
        if actions is not None and (
            not actions
            or not all(isinstance(action, JobAction) for action in actions)
        ):
            raise ValueError("actions must be a non-empty tuple of JobAction values")
        self._prepare()
        with _open_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if actions is None:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at, id
                    LIMIT 1
                    """,
                    (JobStatus.PENDING.value,),
                ).fetchone()
            else:
                placeholders = ",".join("?" for _ in actions)
                row = connection.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE status = ? AND action IN ({placeholders})
                    ORDER BY created_at, id
                    LIMIT 1
                    """,
                    (
                        JobStatus.PENDING.value,
                        *(action.value for action in actions),
                    ),
                ).fetchone()
            if row is None:
                connection.commit()
                return None
            timestamp = _now()
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, attempts = attempts + 1,
                    last_error = NULL
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.RUNNING.value,
                    timestamp,
                    row["id"],
                    JobStatus.PENDING.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.commit()
        return _row_to_job(claimed)

    def _transition(
        self,
        job_id: str,
        *,
        from_statuses: tuple[JobStatus, ...],
        to_status: JobStatus,
        last_error: str | None = None,
    ) -> Job:
        if not self.path.is_file():
            raise KeyError(job_id)
        placeholders = ",".join("?" for _ in from_statuses)
        timestamp = _now()
        with _open_connection(self.path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?, updated_at = ?, last_error = ?
                WHERE id = ? AND status IN ({placeholders})
                """,
                (
                    to_status.value,
                    timestamp,
                    last_error,
                    job_id,
                    *(status.value for status in from_statuses),
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT status FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if exists is None:
                    raise KeyError(job_id)
                raise RuntimeError(
                    f"job {job_id} cannot move from {exists['status']} "
                    f"to {to_status.value}"
                )
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            connection.commit()
        return _row_to_job(row)

    def complete(self, job_id: str) -> Job:
        return self._transition(
            job_id,
            from_statuses=(JobStatus.RUNNING,),
            to_status=JobStatus.COMPLETED,
        )

    def fail(self, job_id: str, error: str, *, retry: bool = False) -> Job:
        message = str(error or "").strip()
        if not message:
            raise ValueError("job failure must include an error")
        return self._transition(
            job_id,
            from_statuses=(JobStatus.RUNNING,),
            to_status=JobStatus.PENDING if retry else JobStatus.FAILED,
            last_error=message,
        )

    def cancel(self, job_id: str) -> Job:
        return self._transition(
            job_id,
            from_statuses=(JobStatus.PENDING, JobStatus.FAILED),
            to_status=JobStatus.CANCELLED,
        )

    def retry(self, job_id: str) -> Job:
        return self._transition(
            job_id,
            from_statuses=(JobStatus.FAILED,),
            to_status=JobStatus.PENDING,
        )

    def recover_interrupted(self) -> int:
        if not self.path.is_file():
            return 0
        with _open_connection(self.path) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?,
                    last_error = 'interrupted before completion'
                WHERE status = ?
                """,
                (
                    JobStatus.PENDING.value,
                    _now(),
                    JobStatus.RUNNING.value,
                ),
            )
            connection.commit()
        return cursor.rowcount
