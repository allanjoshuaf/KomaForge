"""Application operations joining the manifest index with persistent user state."""

from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .library import LibraryIndex
from .library_state import (
    Category,
    LibraryState,
    ReadingProgress,
    TrackedPublication,
    UpdateEvent,
)
from .jobs import Job, JobAction, JobQueue, JobStatus
from .models import Part, Publication
from .paths import canonical_source_identity


@dataclass(frozen=True, slots=True)
class TrackedPublicationView:
    publication: Publication
    tracked: TrackedPublication
    completed_parts: int
    unread_parts: int
    categories: tuple[Category, ...] = ()


@dataclass(frozen=True, slots=True)
class AddedPublication:
    publication: Publication
    tracked: TrackedPublication


@dataclass(frozen=True, slots=True)
class UnreadPartView:
    publication: Publication
    part: Part
    resource_position: int


@dataclass(frozen=True, slots=True)
class ReadingHistoryView:
    publication: Publication
    part: Part
    progress: ReadingProgress


@dataclass(frozen=True, slots=True)
class LibraryUpdateView:
    publication: Publication
    update: UpdateEvent


@dataclass(frozen=True, slots=True)
class ContinuedReading:
    publication: Publication
    part: Part
    path: Path


ExtractionRunner = Callable[[Namespace], int]
ArtifactOpener = Callable[[Path], None]
ReaderLauncher = Callable[..., None]


def _default_artifact_opener(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LibraryService:
    def __init__(self, index: LibraryIndex, state: LibraryState) -> None:
        self.index = index
        self.state = state

    def track(self, publication_id: str) -> TrackedPublication:
        if self.index.load_publication(publication_id) is None:
            raise KeyError(publication_id)
        return self.state.track(publication_id)

    def add_url(
        self,
        source_url: str,
        output_root: Path,
        *,
        options: Mapping[str, object] | None = None,
        runner: ExtractionRunner | None = None,
    ) -> AddedPublication:
        """Extract one URL, refresh the manifest index, then track its publication."""

        from .cli import parse_args
        from .engine import run

        values = dict(options or {})
        arguments = [source_url]
        flags = {
            "chapters": "--chapters",
            "language": "--language",
            "output_format": "--format",
            "scope": "--scope",
            "watermarks": "--watermarks",
            "workers": "--workers",
        }
        unknown = sorted(set(values) - {*flags, "allow_host"})
        if unknown:
            raise ValueError(f"unsupported add option(s): {', '.join(unknown)}")
        for key, flag in flags.items():
            value = values.get(key)
            if value is not None:
                arguments.extend((flag, str(value)))
        allow_hosts = values.get("allow_host") or ()
        if isinstance(allow_hosts, str) or not isinstance(allow_hosts, (list, tuple)):
            raise ValueError("allow_host must be a list of host names")
        for host in allow_hosts:
            arguments.extend(("--allow-host", str(host)))

        args = parse_args(arguments)
        root = output_root.expanduser().resolve()
        args.output_root = root
        args.output_auto_named = True
        args.output = root / ".komaforge" / "incoming"
        exit_code = (runner or run)(args)
        if exit_code != 0:
            raise RuntimeError(f"extraction returned exit code {exit_code}")
        self.index.rebuild(root)
        publication = self.index.find_publication_by_url(source_url)
        if publication is None:
            raise RuntimeError("extraction succeeded but no publication was indexed")
        tracked = self.track(publication.id)
        return AddedPublication(publication, tracked)

    def _part(self, publication: Publication, part_id: str) -> Part:
        for part in publication.parts:
            if part.id == part_id:
                return part
        raise KeyError(part_id)

    def record_progress(
        self,
        publication_id: str,
        part_id: str,
        resource_position: int,
        *,
        completed: bool = False,
    ) -> ReadingProgress:
        publication = self.index.load_publication(publication_id)
        if publication is None:
            raise KeyError(publication_id)
        part = self._part(publication, part_id)
        if part.resources and resource_position > len(part.resources):
            raise ValueError(
                f"resource_position exceeds the part length ({len(part.resources)})"
            )
        return self.state.set_progress(
            publication_id,
            part_id,
            resource_position,
            completed=completed,
        )

    def mark_read(
        self,
        publication_id: str,
        part_id: str | None = None,
    ) -> tuple[ReadingProgress, ...]:
        publication = self.index.load_publication(publication_id)
        if publication is None:
            raise KeyError(publication_id)
        selected = (
            (self._part(publication, part_id),)
            if part_id is not None
            else publication.parts
        )
        self.track(publication_id)
        return tuple(
            self.record_progress(
                publication_id,
                part.id,
                len(part.resources),
                completed=True,
            )
            for part in selected
        )

    def mark_unread(self, publication_id: str, part_id: str | None = None) -> int:
        if self.index.load_publication(publication_id) is None:
            raise KeyError(publication_id)
        return self.state.clear_progress(publication_id, part_id)

    def tracked(self) -> tuple[TrackedPublicationView, ...]:
        views: list[TrackedPublicationView] = []
        for tracked in self.state.tracked():
            publication = self.index.load_publication(tracked.publication_id)
            if publication is None:
                continue
            completed = sum(
                item.completed
                for item in self.state.progress(tracked.publication_id)
                if any(part.id == item.part_id for part in publication.parts)
            )
            views.append(
                TrackedPublicationView(
                    publication=publication,
                    tracked=tracked,
                    completed_parts=completed,
                    unread_parts=max(0, len(publication.parts) - completed),
                    categories=self.state.publication_categories(publication.id),
                )
            )
        return tuple(views)

    def categorized(self, name: str) -> tuple[Publication, ...]:
        publications: list[Publication] = []
        for publication_id in self.state.category_members(name):
            publication = self.index.load_publication(publication_id)
            if publication is not None:
                publications.append(publication)
        return tuple(
            sorted(publications, key=lambda item: (item.title.casefold(), item.id))
        )

    def dashboard(self, queue: JobQueue) -> dict:
        """Return one stable snapshot for terminal and future graphical clients."""

        jobs = queue.list()
        return {
            **self.index.status(),
            "downloaded": len(self.index.list_downloaded()),
            "tracked": len(self.tracked()),
            "categories": len(self.state.categories()),
            "unread": len(self.unread()),
            "updates": len(self.updates(unseen_only=True)),
            "history": len(self.history()),
            "jobs": {
                status.value: sum(job.status is status for job in jobs)
                for status in JobStatus
            },
        }

    def unread(self, publication_id: str | None = None) -> tuple[UnreadPartView, ...]:
        """List tracked parts that have not been explicitly completed."""

        views: list[UnreadPartView] = []
        tracked = self.state.tracked()
        if publication_id is not None:
            tracked = tuple(
                item for item in tracked if item.publication_id == publication_id
            )
            if not tracked:
                raise KeyError(publication_id)
        for tracked_publication in tracked:
            publication = self.index.load_publication(
                tracked_publication.publication_id
            )
            if publication is None:
                continue
            progress = {
                item.part_id: item
                for item in self.state.progress(tracked_publication.publication_id)
            }
            for part in publication.parts:
                current = progress.get(part.id)
                if current is not None and current.completed:
                    continue
                views.append(
                    UnreadPartView(
                        publication=publication,
                        part=part,
                        resource_position=(
                            current.resource_position if current is not None else 0
                        ),
                    )
                )
        return tuple(views)

    def updates(self, *, unseen_only: bool = False) -> tuple[LibraryUpdateView, ...]:
        """List newly discovered parts independently from reading progress."""

        views: list[LibraryUpdateView] = []
        for update in self.state.updates(unseen_only=unseen_only):
            publication = self.index.load_publication(update.publication_id)
            if publication is not None:
                views.append(LibraryUpdateView(publication, update))
        return tuple(views)

    def mark_updates_seen(self, publication_id: str | None = None) -> int:
        if publication_id is not None:
            tracked = {
                item.publication_id for item in self.state.tracked()
            }
            if publication_id not in tracked:
                raise KeyError(publication_id)
        return self.state.mark_updates_seen(publication_id)

    def queue_updates(
        self,
        queue: JobQueue,
        publication_id: str | None = None,
    ) -> tuple[Job, ...]:
        """Queue one update check per tracked publication without active duplicates."""

        tracked = self.state.tracked()
        if publication_id is not None:
            tracked = tuple(
                item for item in tracked if item.publication_id == publication_id
            )
            if not tracked:
                raise KeyError(publication_id)
        active = {
            canonical_source_identity(job.source_url)
            for job in queue.list()
            if job.action is JobAction.UPDATE
            and job.status in {JobStatus.PENDING, JobStatus.RUNNING}
        }
        queued: list[Job] = []
        for item in tracked:
            publication = self.index.load_publication(item.publication_id)
            if publication is None:
                continue
            identity = canonical_source_identity(publication.source_url)
            if identity in active:
                continue
            options = {}
            language = publication.metadata.get("language")
            if isinstance(language, str) and language.strip():
                options["language"] = language
            queued.append(
                queue.enqueue(
                    JobAction.UPDATE,
                    publication.source_url,
                    options=options,
                )
            )
            active.add(identity)
        return tuple(queued)

    def open_artifact(
        self,
        publication_id: str,
        *,
        opener: ArtifactOpener | None = None,
    ) -> Path:
        paths = self.index.artifact_paths(publication_id)
        if not paths:
            raise FileNotFoundError("publication has no available local artifact")
        path = paths[0]
        (opener or _default_artifact_opener)(path)
        return path

    def read_artifact(
        self,
        publication_id: str,
        *,
        part_id: str | None = None,
        launcher: ReaderLauncher | None = None,
    ) -> Path:
        """Read a CBZ or image folder locally and persist its page position."""

        from .reader import ReaderDocument, serve_reader

        publication = self.index.load_publication(publication_id)
        if publication is None:
            raise KeyError(publication_id)
        if not publication.parts:
            raise ValueError("publication has no readable part")
        paths = self.index.artifact_paths(publication_id)
        if not paths:
            raise FileNotFoundError("publication has no available local artifact")

        ordered_parts = tuple(sorted(publication.parts, key=lambda item: item.position))
        progress = {item.part_id: item for item in self.state.progress(publication.id)}
        if part_id is not None:
            part = self._part(publication, part_id)
        else:
            unfinished = [
                item
                for item in reversed(self.state.progress(publication.id))
                if not item.completed and any(part.id == item.part_id for part in ordered_parts)
            ]
            completed_ids = {
                item.part_id for item in progress.values() if item.completed
            }
            part = (
                self._part(publication, unfinished[0].part_id)
                if unfinished
                else next(
                    (item for item in ordered_parts if item.id not in completed_ids),
                    ordered_parts[0],
                )
            )

        part_index = ordered_parts.index(part)
        if len(ordered_parts) == 1:
            path = paths[0]
        elif len(paths) == len(ordered_parts):
            path = paths[part_index]
        else:
            raise FileNotFoundError(
                "publication artifacts cannot be matched safely to the requested part"
            )
        document = ReaderDocument.from_path(path)
        if part.resources and len(document.pages) != len(part.resources):
            raise ValueError(
                "artifact page count does not match the indexed part "
                f"({len(document.pages)} != {len(part.resources)})"
            )
        self.track(publication.id)
        current = progress.get(part.id)
        start_position = current.resource_position if current else 1

        def save_progress(position: int, completed: bool) -> None:
            self.record_progress(
                publication.id,
                part.id,
                position,
                completed=completed,
            )

        (launcher or serve_reader)(
            document,
            title=(
                publication.title
                if len(ordered_parts) == 1
                else f"{publication.title} — {part.title}"
            ),
            start_position=start_position,
            progress_callback=save_progress,
        )
        return document.path

    def continue_reading(
        self,
        *,
        launcher: ReaderLauncher | None = None,
    ) -> ContinuedReading:
        """Open the most recent unfinished local reading, or the newest unread one."""

        candidates: list[tuple[Publication, Part]] = []
        seen: set[str] = set()
        for item in self.history():
            if item.progress.completed or item.part.id in seen:
                continue
            candidates.append((item.publication, item.part))
            seen.add(item.part.id)
        for tracked in reversed(self.state.tracked()):
            publication = self.index.load_publication(tracked.publication_id)
            if publication is None:
                continue
            completed_ids = {
                item.part_id
                for item in self.state.progress(publication.id)
                if item.completed
            }
            for part in sorted(publication.parts, key=lambda item: item.position):
                if part.id not in completed_ids and part.id not in seen:
                    candidates.append((publication, part))
                    seen.add(part.id)

        if not candidates:
            raise ValueError("no unfinished local reading is available")
        publication, part = candidates[0]
        path = self.read_artifact(
            publication.id,
            part_id=part.id,
            launcher=launcher,
        )
        return ContinuedReading(publication, part, path)

    def history(self) -> tuple[ReadingHistoryView, ...]:
        """Return known reading progress with the most recent item first."""

        history: list[ReadingHistoryView] = []
        for progress in reversed(self.state.progress()):
            publication = self.index.load_publication(progress.publication_id)
            if publication is None:
                continue
            part = next(
                (item for item in publication.parts if item.id == progress.part_id),
                None,
            )
            if part is None:
                continue
            history.append(ReadingHistoryView(publication, part, progress))
        return tuple(history)
