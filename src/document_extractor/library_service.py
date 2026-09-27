"""Application operations joining the manifest index with persistent user state."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .library import LibraryIndex
from .library_state import LibraryState, ReadingProgress, TrackedPublication
from .models import Part, Publication


@dataclass(frozen=True, slots=True)
class TrackedPublicationView:
    publication: Publication
    tracked: TrackedPublication
    completed_parts: int
    unread_parts: int


@dataclass(frozen=True, slots=True)
class AddedPublication:
    publication: Publication
    tracked: TrackedPublication


ExtractionRunner = Callable[[Namespace], int]


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
                )
            )
        return tuple(views)
