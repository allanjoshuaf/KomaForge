"""Public MangaDex catalog, chapter, and image adapter."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import urlencode, urlparse

from ..models import (
    Confidence,
    Coverage,
    Part,
    PartKind,
    Publication,
    Resource,
    ResourceKind,
    UpdateResult,
    Work,
)
from ..updates import compare_part_updates
from .catalog import SourceAccess, SourceMetadata, SourceStatus
from .contracts import (
    MatchContext,
    MatchResult,
    ResourceSet,
    SearchPage,
    SourceReference,
    SourceSession,
)


API_ROOT = "https://api.mangadex.org"
SITE_ROOT = "https://mangadex.org"
_PATH = re.compile(
    r"^/(?P<kind>title|chapter)/(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/[^/]+)?/?$",
    re.IGNORECASE,
)
JsonFetcher = Callable[[str, Mapping[str, object] | None], dict]


def _fetch_json(url: str, parameters: Mapping[str, object] | None = None) -> dict:
    query = urlencode(parameters or {}, doseq=True)
    target = f"{url}?{query}" if query else url
    request = urllib.request.Request(
        target,
        headers={
            "Accept": "application/json",
            "User-Agent": "KomaForge/0.4.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError("MangaDex API request failed") from exc
    if not isinstance(payload, dict) or payload.get("result") != "ok":
        raise RuntimeError("MangaDex API returned an invalid response")
    return payload


def _path_reference(value: str) -> tuple[str, str] | None:
    parsed = urlparse(value)
    if (parsed.hostname or "").casefold() not in {"mangadex.org", "www.mangadex.org"}:
        return None
    match = _PATH.fullmatch(parsed.path)
    if match is None:
        return None
    return match.group("kind").casefold(), match.group("id").casefold()


def _localized(values: object, preferred: str = "en") -> str:
    if not isinstance(values, Mapping):
        return ""
    for key in (preferred, "en", "ja-ro", "ja"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return next(
        (
            value.strip()
            for value in values.values()
            if isinstance(value, str) and value.strip()
        ),
        "",
    )


def _language(value: object) -> str:
    return {
        "zh": "zh-hans",
        "zh-cn": "zh-hans",
        "zh-tw": "zh-hk",
    }.get(str(value or "en").casefold(), str(value or "en").casefold())


def _relationship_names(item: Mapping[str, object], kind: str) -> tuple[str, ...]:
    relationships = item.get("relationships")
    if not isinstance(relationships, list):
        return ()
    return tuple(
        str(attributes["name"]).strip()
        for relationship in relationships
        if isinstance(relationship, Mapping)
        and relationship.get("type") == kind
        and isinstance((attributes := relationship.get("attributes")), Mapping)
        and isinstance(attributes.get("name"), str)
        and str(attributes["name"]).strip()
    )


def _cover_url(item: Mapping[str, object]) -> str | None:
    relationships = item.get("relationships")
    if not isinstance(relationships, list):
        return None
    manga_id = str(item.get("id") or "")
    for relationship in relationships:
        if not isinstance(relationship, Mapping) or relationship.get("type") != "cover_art":
            continue
        attributes = relationship.get("attributes")
        if isinstance(attributes, Mapping) and attributes.get("fileName"):
            return (
                f"https://uploads.mangadex.org/covers/{manga_id}/"
                f"{attributes['fileName']}.256.jpg"
            )
    return None


def _work_from_item(item: Mapping[str, object], preferred_language: str) -> Work:
    manga_id = str(item.get("id") or "").strip()
    attributes = item.get("attributes")
    if not manga_id or not isinstance(attributes, Mapping):
        raise RuntimeError("MangaDex manga record is incomplete")
    title = _localized(attributes.get("title"), preferred_language) or "MangaDex title"
    work_id = f"work-mangadex-{manga_id}"
    publication = Publication(
        id=f"publication-mangadex-{manga_id}",
        work_id=work_id,
        source_id=MangaDexSource.id,
        title=title,
        source_url=f"{SITE_ROOT}/title/{manga_id}",
        metadata={"attribution": "MangaDex"},
    )
    tags = attributes.get("tags")
    genres = tuple(
        name
        for tag in tags if isinstance(tags, list) and isinstance(tag, Mapping)
        if isinstance((tag_attributes := tag.get("attributes")), Mapping)
        if (name := _localized(tag_attributes.get("name"), preferred_language))
    ) if isinstance(tags, list) else ()
    return Work(
        id=work_id,
        title=title,
        publications=(publication,),
        authors=_relationship_names(item, "author"),
        artists=_relationship_names(item, "artist"),
        genres=genres,
        cover_url=_cover_url(item),
        metadata={
            "attribution": "MangaDex",
            "status": attributes.get("status"),
        },
    )


class MangaDexSource:
    id = "mangadex"
    name = "MangaDex"
    metadata = SourceMetadata(
        languages=("mul",),
        domains=("mangadex.org", "www.mangadex.org"),
        version="1",
        status=SourceStatus.EXPERIMENTAL,
        status_reason="public API flow is implemented; broader live baselines are pending",
        access=SourceAccess.VARIABLE,
        family_ids=("paginated-images",),
        last_verified="2026-09-28",
    )

    def __init__(self, fetch_json: JsonFetcher | None = None) -> None:
        self._fetch = fetch_json or _fetch_json

    def match(self, url: str, context: MatchContext) -> MatchResult:
        if _path_reference(url) is None:
            return MatchResult.no_match("not a MangaDex title or chapter URL")
        return MatchResult.recognized(
            "official MangaDex title or chapter URL",
            confidence=Confidence.HIGH,
        )

    def _manga_item(self, manga_id: str) -> dict:
        payload = self._fetch(
            f"{API_ROOT}/manga/{manga_id}",
            {"includes[]": ("author", "artist", "cover_art")},
        )
        item = payload.get("data")
        if not isinstance(item, dict):
            raise RuntimeError("MangaDex returned no manga record")
        return item

    def _chapter_item(self, chapter_id: str) -> dict:
        payload = self._fetch(
            f"{API_ROOT}/chapter/{chapter_id}",
            {"includes[]": ("manga", "scanlation_group")},
        )
        item = payload.get("data")
        if not isinstance(item, dict):
            raise RuntimeError("MangaDex returned no chapter record")
        return item

    @staticmethod
    def _manga_relationship(item: Mapping[str, object]) -> str:
        relationships = item.get("relationships")
        if isinstance(relationships, list):
            for relationship in relationships:
                if isinstance(relationship, Mapping) and relationship.get("type") == "manga":
                    manga_id = str(relationship.get("id") or "").strip()
                    if manga_id:
                        return manga_id
        raise RuntimeError("MangaDex chapter has no manga relationship")

    def _feed(self, manga_id: str, language: str) -> tuple[list[dict], int]:
        records: list[dict] = []
        offset = 0
        total = 0
        while True:
            payload = self._fetch(
                f"{API_ROOT}/manga/{manga_id}/feed",
                {
                    "limit": 100,
                    "offset": offset,
                    "translatedLanguage[]": (language,),
                    "order[volume]": "asc",
                    "order[chapter]": "asc",
                    "includes[]": ("scanlation_group",),
                    "includeFutureUpdates": "0",
                    "includeEmptyPages": "0",
                },
            )
            data = payload.get("data")
            if not isinstance(data, list):
                raise RuntimeError("MangaDex chapter feed is invalid")
            records.extend(item for item in data if isinstance(item, dict))
            total = int(payload.get("total") or len(records))
            offset += len(data)
            if not data or offset >= total:
                break
            if offset >= 5000:
                raise RuntimeError("MangaDex chapter feed exceeds the safety limit")
        return records, total

    @staticmethod
    def _part(item: Mapping[str, object], position: int) -> Part:
        chapter_id = str(item.get("id") or "").strip()
        attributes = item.get("attributes")
        if not chapter_id or not isinstance(attributes, Mapping):
            raise RuntimeError("MangaDex chapter record is incomplete")
        number = str(attributes.get("chapter") or position)
        volume = str(attributes.get("volume") or "").strip()
        subtitle = str(attributes.get("title") or "").strip()
        labels = [f"Chapter {number}"]
        if volume:
            labels.insert(0, f"Volume {volume}")
        if subtitle:
            labels.append(subtitle)
        groups = _relationship_names(item, "scanlation_group")
        pages = int(attributes.get("pages") or 0)
        return Part(
            id=f"part-mangadex-{chapter_id}",
            kind=PartKind.CHAPTER,
            title=" — ".join(labels),
            position=position,
            number=number,
            source_url=f"{SITE_ROOT}/chapter/{chapter_id}",
            coverage=Coverage.from_counts(
                0,
                pages or None,
                unit="resources",
                evidence="MangaDex chapter metadata",
                confidence=Confidence.HIGH,
            ),
            metadata={
                "chapter_id": chapter_id,
                "translated_language": attributes.get("translatedLanguage"),
                "scanlation_groups": groups,
                "attribution": "MangaDex",
            },
        )

    def get_publication(
        self,
        reference: SourceReference,
        session: SourceSession,
    ) -> Publication:
        if reference.source_id != self.id:
            raise ValueError("reference belongs to another source")
        parsed = _path_reference(reference.url or reference.value)
        if parsed is None:
            raise ValueError("reference is not a MangaDex title or chapter URL")
        kind, identifier = parsed
        selected_chapter = self._chapter_item(identifier) if kind == "chapter" else None
        manga_id = (
            self._manga_relationship(selected_chapter)
            if selected_chapter is not None
            else identifier
        )
        language = _language(session.options.get("language"))
        work = _work_from_item(self._manga_item(manga_id), language)
        if selected_chapter is not None:
            chapter_items = [selected_chapter]
            total = 1
        else:
            chapter_items, total = self._feed(manga_id, language)
        parts = tuple(
            self._part(item, position)
            for position, item in enumerate(chapter_items, start=1)
            if not (item.get("attributes") or {}).get("externalUrl")
            and int((item.get("attributes") or {}).get("pages") or 0) > 0
        )
        if not parts:
            raise RuntimeError(
                f"MangaDex exposes no downloadable {language} chapter for this title"
            )
        publication = work.publications[0]
        return Publication(
            id=publication.id,
            work_id=publication.work_id,
            source_id=self.id,
            title=publication.title,
            source_url=publication.source_url,
            parts=parts,
            coverage=Coverage.from_counts(
                len(parts),
                total,
                unit="parts",
                evidence="MangaDex chapter feed",
                confidence=Confidence.HIGH,
                source_limited=len(parts) < total,
                detail=(
                    "Some catalog entries point to external chapters or expose no pages."
                    if len(parts) < total
                    else None
                ),
            ),
            metadata={
                **dict(publication.metadata),
                "publication_type": "work" if len(parts) > 1 else "document",
                "language": str(session.options.get("language") or "en"),
                "source_language": language,
            },
        )

    def get_parts(
        self,
        publication: Publication,
        session: SourceSession,
    ) -> tuple[Part, ...]:
        if publication.source_id != self.id:
            raise ValueError("publication belongs to another source")
        return publication.parts

    def get_resources(self, part: Part, session: SourceSession) -> ResourceSet:
        chapter_id = str(part.metadata.get("chapter_id") or "").strip()
        if not chapter_id:
            parsed = _path_reference(part.source_url)
            chapter_id = parsed[1] if parsed and parsed[0] == "chapter" else ""
        if not chapter_id:
            raise ValueError("MangaDex part has no chapter identifier")
        payload = self._fetch(
            f"{API_ROOT}/at-home/server/{chapter_id}",
            {"forcePort443": "true"},
        )
        base_url = str(payload.get("baseUrl") or "").rstrip("/")
        chapter = payload.get("chapter")
        if not base_url or not isinstance(chapter, Mapping):
            raise RuntimeError("MangaDex at-home response is incomplete")
        digest = str(chapter.get("hash") or "").strip()
        files = chapter.get("data")
        if not digest or not isinstance(files, list) or not files:
            raise RuntimeError("MangaDex chapter exposes no original pages")
        resources = tuple(
            Resource(
                id=f"resource-mangadex-{chapter_id}-{position}",
                kind=ResourceKind.IMAGE,
                locator=f"{base_url}/data/{digest}/{filename}",
                position=position,
                filename=str(filename),
                metadata={
                    "attribution": "MangaDex",
                    "scanlation_groups": part.metadata.get("scanlation_groups", ()),
                },
            )
            for position, filename in enumerate(files, start=1)
        )
        return ResourceSet(
            resources,
            Coverage.from_counts(
                len(resources),
                len(resources),
                unit="resources",
                evidence="MangaDex at-home manifest",
                confidence=Confidence.HIGH,
            ),
        )

    def _search_page(
        self,
        *,
        page: int,
        language: str,
        query: str | None = None,
        order: Mapping[str, str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> SearchPage:
        limit = 20
        parameters: dict[str, object] = {
            "limit": limit,
            "offset": (page - 1) * limit,
            "includes[]": ("author", "artist", "cover_art"),
            "contentRating[]": ("safe", "suggestive"),
            "availableTranslatedLanguage[]": (language,),
        }
        if query:
            parameters["title"] = query
        for key, value in dict(filters or {}).items():
            if key not in {"status[]", "publicationDemographic[]", "includedTags[]"}:
                raise ValueError(f"unsupported MangaDex search filter: {key}")
            parameters[key] = value
        parameters.update(order or {})
        payload = self._fetch(f"{API_ROOT}/manga", parameters)
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("MangaDex search response is invalid")
        total = int(payload.get("total") or len(data))
        return SearchPage(
            tuple(
                _work_from_item(item, language)
                for item in data
                if isinstance(item, Mapping)
            ),
            page,
            (page * limit) < total,
        )

    def search(
        self,
        query: str,
        filters: Mapping[str, object],
        page: int,
        session: SourceSession,
    ) -> SearchPage:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search query cannot be empty")
        return self._search_page(
            page=page,
            language=_language(session.options.get("language")),
            query=query.strip(),
            filters=filters,
            order={"order[relevance]": "desc"},
        )

    def popular(self, page: int, session: SourceSession) -> SearchPage:
        return self._search_page(
            page=page,
            language=_language(session.options.get("language")),
            order={"order[followedCount]": "desc"},
        )

    def latest(self, page: int, session: SourceSession) -> SearchPage:
        return self._search_page(
            page=page,
            language=_language(session.options.get("language")),
            order={"order[latestUploadedChapter]": "desc"},
        )

    def check_updates(
        self,
        publication: Publication,
        known_parts: tuple[Part, ...],
        session: SourceSession,
    ) -> UpdateResult:
        if publication.source_id != self.id:
            raise ValueError("publication belongs to another source")
        return compare_part_updates(publication, known_parts, publication.parts)
