from __future__ import annotations

import argparse
import json
import sys

from .application import resolve_source
from .sources import (
    BUILTIN_READER_FAMILIES,
    BUILTIN_SOURCE_CANDIDATES,
    BrowseCapability,
    GenericWebSource,
    SearchCapability,
    SourceStatus,
    UpdateCapability,
    build_default_registry,
    metadata_for,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge-sources",
        description="Liste les sources KomaForge et explique le routage d’une URL.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Liste les adaptateurs disponibles")
    listing.add_argument("--json", action="store_true", dest="as_json")
    listing.add_argument(
        "--status",
        choices=[status.value for status in SourceStatus],
        help="Filtre les adaptateurs par état",
    )
    families = commands.add_parser(
        "families",
        help="Liste les familles de lecteurs réutilisables",
    )
    families.add_argument("--json", action="store_true", dest="as_json")
    families.add_argument(
        "--status",
        choices=[status.value for status in SourceStatus],
        help="Filtre les familles par état",
    )
    candidates = commands.add_parser(
        "candidates",
        help="Liste les sites connus sans adaptateur spécialisé",
    )
    candidates.add_argument("--json", action="store_true", dest="as_json")
    candidates.add_argument(
        "--status",
        choices=[status.value for status in SourceStatus],
        help="Filtre les sites candidats par état",
    )
    match = commands.add_parser("match", help="Indique la source choisie pour une URL")
    match.add_argument("url")
    match.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _source_payload(adapter, *, specialized: bool) -> dict:
    metadata = metadata_for(adapter)
    return {
        "id": adapter.id,
        "name": adapter.name,
        "specialized": specialized,
        "languages": list(metadata.languages),
        "domains": list(metadata.domains),
        "version": metadata.version,
        "status": metadata.status.value,
        "status_reason": metadata.status_reason,
        "families": list(metadata.family_ids),
        "last_verified": metadata.last_verified,
        "capabilities": {
            "url": True,
            "publication": True,
            "parts": True,
            "resources": True,
            "browse": isinstance(adapter, BrowseCapability),
            "search": isinstance(adapter, SearchCapability),
            "update": isinstance(adapter, UpdateCapability),
        },
    }


def _sources() -> tuple[dict, ...]:
    registry = build_default_registry()
    specialized = tuple(
        _source_payload(adapter, specialized=True)
        for adapter in registry.all()
    )
    return specialized + (_source_payload(GenericWebSource(), specialized=False),)


def _families() -> tuple[dict, ...]:
    return tuple(
        {
            "id": family.id,
            "name": family.name,
            "status": family.status.value,
            "description": family.description,
        }
        for family in BUILTIN_READER_FAMILIES
    )


def _candidates() -> tuple[dict, ...]:
    return tuple(
        {
            "id": candidate.id,
            "name": candidate.name,
            "languages": list(candidate.languages),
            "domains": list(candidate.domains),
            "status": candidate.status.value,
            "status_reason": candidate.status_reason,
            "adapter_id": candidate.adapter_id,
            "families": list(candidate.family_ids),
            "last_verified": candidate.last_verified,
        }
        for candidate in BUILTIN_SOURCE_CANDIDATES
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            sources = _sources()
            if args.status:
                sources = tuple(
                    source for source in sources if source["status"] == args.status
                )
            if args.as_json:
                print(json.dumps(sources, ensure_ascii=False, sort_keys=True))
            else:
                for source in sources:
                    capabilities = ", ".join(
                        name
                        for name, enabled in source["capabilities"].items()
                        if enabled
                    ) or "URL"
                    source_type = "spécialisée" if source["specialized"] else "fallback"
                    print(
                        f"{source['id']} | {source['name']} | {source_type} | "
                        f"{source['status']} | {','.join(source['languages'])} | "
                        f"{','.join(source['domains'])} | v{source['version']} | "
                        f"{capabilities}"
                    )
            return 0

        if args.command == "families":
            families = _families()
            if args.status:
                families = tuple(
                    family for family in families if family["status"] == args.status
                )
            if args.as_json:
                print(json.dumps(families, ensure_ascii=False, sort_keys=True))
            else:
                for family in families:
                    print(
                        f"{family['id']} | {family['name']} | "
                        f"{family['status']} | {family['description']}"
                    )
            return 0

        if args.command == "candidates":
            candidates = _candidates()
            if args.status:
                candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate["status"] == args.status
                )
            if args.as_json:
                print(json.dumps(candidates, ensure_ascii=False, sort_keys=True))
            else:
                for candidate in candidates:
                    print(
                        f"{candidate['id']} | {candidate['name']} | "
                        f"{candidate['status']} | {','.join(candidate['languages'])} | "
                        f"{','.join(candidate['domains'])} | {candidate['adapter_id']} | "
                        f"vérifié {candidate['last_verified'] or 'jamais'}"
                    )
            return 0

        route = resolve_source(args.url)
        payload = {
            **_source_payload(route.adapter, specialized=route.specialized),
            "confidence": route.match.confidence.value,
            "reason": route.match.reason,
        }
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"{payload['id']} | {payload['name']} | "
                f"confiance {payload['confidence']} | {payload['reason']}"
            )
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur de source : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
