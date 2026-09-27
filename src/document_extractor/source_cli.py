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
    SourceAccess,
    SourceIntegration,
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
    listing.add_argument(
        "--integration",
        choices=[value.value for value in SourceIntegration],
        help="Filtre les adaptateurs par type d’intégration",
    )
    listing.add_argument(
        "--access",
        choices=[value.value for value in SourceAccess],
        help="Filtre les adaptateurs par condition d’accès",
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
    candidates.add_argument(
        "--integration",
        choices=[value.value for value in SourceIntegration],
        help="Filtre les sites par type d’intégration",
    )
    candidates.add_argument(
        "--access",
        choices=[value.value for value in SourceAccess],
        help="Filtre les sites par condition d’accès",
    )
    match = commands.add_parser("match", help="Indique la source choisie pour une URL")
    match.add_argument("url")
    match.add_argument("--json", action="store_true", dest="as_json")
    return parser


def describe_source(adapter, *, specialized: bool) -> dict:
    metadata = metadata_for(adapter)
    return {
        "id": adapter.id,
        "name": adapter.name,
        "specialized": specialized,
        "languages": list(metadata.languages),
        "domains": list(metadata.domains),
        "version": metadata.version,
        "status": metadata.status.value,
        "compatibility": metadata.status.value,
        "status_reason": metadata.status_reason,
        "integration": metadata.integration.value,
        "access": metadata.access.value,
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


def source_records() -> tuple[dict, ...]:
    registry = build_default_registry()
    specialized = tuple(
        describe_source(adapter, specialized=True)
        for adapter in registry.all()
    )
    return specialized + (describe_source(GenericWebSource(), specialized=False),)


def family_records() -> tuple[dict, ...]:
    return tuple(
        {
            "id": family.id,
            "name": family.name,
            "status": family.status.value,
            "description": family.description,
        }
        for family in BUILTIN_READER_FAMILIES
    )


def candidate_records() -> tuple[dict, ...]:
    return tuple(
        {
            "id": candidate.id,
            "name": candidate.name,
            "languages": list(candidate.languages),
            "domains": list(candidate.domains),
            "status": candidate.status.value,
            "compatibility": candidate.status.value,
            "status_reason": candidate.status_reason,
            "integration": candidate.integration.value,
            "access": candidate.access.value,
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
            sources = source_records()
            if args.status:
                sources = tuple(
                    source for source in sources if source["status"] == args.status
                )
            if args.integration:
                sources = tuple(
                    source
                    for source in sources
                    if source["integration"] == args.integration
                )
            if args.access:
                sources = tuple(
                    source for source in sources if source["access"] == args.access
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
                    print(
                        f"{source['id']} | {source['name']} | "
                        f"compatibilité {source['compatibility']} | "
                        f"intégration {source['integration']} | accès {source['access']} | "
                        f"{','.join(source['languages'])} | "
                        f"{','.join(source['domains'])} | v{source['version']} | "
                        f"{capabilities}"
                    )
            return 0

        if args.command == "families":
            families = family_records()
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
            candidates = candidate_records()
            if args.status:
                candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate["status"] == args.status
                )
            if args.integration:
                candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate["integration"] == args.integration
                )
            if args.access:
                candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate["access"] == args.access
                )
            if args.as_json:
                print(json.dumps(candidates, ensure_ascii=False, sort_keys=True))
            else:
                for candidate in candidates:
                    print(
                        f"{candidate['id']} | {candidate['name']} | "
                        f"compatibilité {candidate['compatibility']} | "
                        f"intégration {candidate['integration']} | "
                        f"accès {candidate['access']} | "
                        f"{','.join(candidate['languages'])} | "
                        f"{','.join(candidate['domains'])} | {candidate['adapter_id']} | "
                        f"vérifié {candidate['last_verified'] or 'jamais'}"
                    )
            return 0

        route = resolve_source(args.url)
        payload = {
            **describe_source(route.adapter, specialized=route.specialized),
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
