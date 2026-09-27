"""Application operations joining the manifest index with persistent user state."""

from __future__ import annotations

from dataclasses import dataclass

from .library import LibraryIndex
from .library_state import LibraryState, ReadingProgress, TrackedPublication
from .models import Part, Publication


@dataclass(frozen=True, slots=True)
class TrackedPublicationView:
    publication: Publication
    tracked: TrackedPublication
    completed_parts: int
    unread_parts: int


class LibraryService:
    def __init__(self, index: LibraryIndex, state: LibraryState) -> None:
        self.index = index
        self.state = state

    def track(self, publication_id: str) -> TrackedPublication:
        if self.index.load_publication(publication_id) is None:
            raise KeyError(publication_id)
        return self.state.track(publication_id)

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
