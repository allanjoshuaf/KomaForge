from __future__ import annotations

import argparse
import json
import sys

from .application import resolve_source
from .sources import (
    BrowseCapability,
    GenericWebSource,
    SearchCapability,
    UpdateCapability,
    build_default_registry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komaforge-sources",
        description="Liste les sources KomaForge et explique le routage d’une URL.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Liste les adaptateurs disponibles")
    listing.add_argument("--json", action="store_true", dest="as_json")
    match = commands.add_parser("match", help="Indique la source choisie pour une URL")
    match.add_argument("url")
    match.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _source_payload(adapter, *, specialized: bool) -> dict:
    return {
        "id": adapter.id,
        "name": adapter.name,
        "specialized": specialized,
        "capabilities": {
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            sources = _sources()
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
                        f"{capabilities}"
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
