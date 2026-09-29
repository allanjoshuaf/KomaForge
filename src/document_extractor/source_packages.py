"""Read-only inspection of third-party source package manifests."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .sources import BUILTIN_READER_FAMILIES, build_default_registry


SOURCE_PACKAGE_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_LANGUAGE = re.compile(r"^(?:[a-z]{2,3}|mul|und)$")
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_CAPABILITIES = {"url", "search", "browse", "update"}


def default_source_packages_dir() -> Path:
    configured = os.environ.get("KOMAFORGE_SOURCES_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return (
            Path(os.environ["LOCALAPPDATA"]) / "KomaForge" / "Sources"
        ).resolve()
    return (Path.home() / ".komaforge" / "sources").resolve()


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _text_tuple(
    payload: Mapping[str, object],
    key: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    values = payload.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} must be a non-empty array")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} entries must be non-empty strings")
        item = value.strip().casefold()
        if pattern is not None and pattern.fullmatch(item) is None:
            raise ValueError(f"invalid {key} entry: {value!r}")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class SourcePackageManifest:
    id: str
    name: str
    version: str
    languages: tuple[str, ...]
    domains: tuple[str, ...]
    families: tuple[str, ...]
    capabilities: tuple[str, ...]
    network_domains: tuple[str, ...]
    browser: bool
    schema_version: int = SOURCE_PACKAGE_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> SourcePackageManifest:
        if not isinstance(payload, Mapping):
            raise ValueError("source package manifest must be an object")
        allowed_fields = {
            "schema_version",
            "id",
            "name",
            "version",
            "languages",
            "domains",
            "families",
            "capabilities",
            "permissions",
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("unknown manifest fields: " + ", ".join(unknown_fields))
        schema_version = payload.get("schema_version")
        if schema_version != SOURCE_PACKAGE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported source package schema version: {schema_version!r}"
            )
        if "entrypoint" in payload or "python" in payload:
            raise ValueError(
                "executable extensions are disabled until an isolated runtime exists"
            )
        source_id = _required_text(payload, "id").casefold()
        if _IDENTIFIER.fullmatch(source_id) is None:
            raise ValueError("id must use lowercase letters, numbers, and hyphens")
        languages = _text_tuple(payload, "languages", pattern=_LANGUAGE)
        domains = _text_tuple(payload, "domains", pattern=_DOMAIN)
        families = _text_tuple(payload, "families", pattern=_IDENTIFIER)
        known_families = {family.id for family in BUILTIN_READER_FAMILIES}
        unknown_families = sorted(set(families) - known_families)
        if unknown_families:
            raise ValueError(
                "unknown reader families: " + ", ".join(unknown_families)
            )
        capabilities = _text_tuple(payload, "capabilities", pattern=_IDENTIFIER)
        unknown_capabilities = sorted(set(capabilities) - _CAPABILITIES)
        if unknown_capabilities:
            raise ValueError(
                "unknown capabilities: " + ", ".join(unknown_capabilities)
            )
        permissions = payload.get("permissions", {})
        if not isinstance(permissions, Mapping):
            raise ValueError("permissions must be an object")
        unknown_permissions = sorted(
            set(permissions) - {"network_domains", "browser", "filesystem"}
        )
        if unknown_permissions:
            raise ValueError(
                "unknown permissions: " + ", ".join(unknown_permissions)
            )
        filesystem = permissions.get("filesystem", "none")
        if filesystem != "none":
            raise ValueError("third-party source packages cannot request filesystem access")
        browser = permissions.get("browser", False)
        if not isinstance(browser, bool):
            raise ValueError("permissions.browser must be a boolean")
        permission_payload = {
            "network_domains": permissions.get("network_domains", list(domains))
        }
        network_domains = _text_tuple(
            permission_payload,
            "network_domains",
            pattern=_DOMAIN,
        )
        return cls(
            id=source_id,
            name=_required_text(payload, "name"),
            version=_required_text(payload, "version"),
            languages=languages,
            domains=domains,
            families=families,
            capabilities=capabilities,
            network_domains=network_domains,
            browser=browser,
            schema_version=schema_version,
        )


@dataclass(frozen=True, slots=True)
class SourcePackageInspection:
    path: Path
    manifest: SourcePackageManifest | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.manifest is not None and self.error is None


def inspect_source_package(path: Path) -> SourcePackageInspection:
    resolved = path.expanduser().resolve()
    try:
        if path.is_symlink():
            raise ValueError("symbolic-link manifests are not accepted")
        if not resolved.is_file():
            raise ValueError("manifest is not a regular file")
        if resolved.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds the 64 KiB limit")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        manifest = SourcePackageManifest.from_mapping(payload)
        builtin_ids = {adapter.id for adapter in build_default_registry().all()}
        builtin_ids.add("generic-web")
        if manifest.id in builtin_ids:
            raise ValueError(f"source id conflicts with a built-in source: {manifest.id}")
        return SourcePackageInspection(resolved, manifest)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return SourcePackageInspection(resolved, None, str(exc))


def inspect_source_packages(directory: Path) -> tuple[SourcePackageInspection, ...]:
    root = directory.expanduser().resolve()
    if not root.is_dir():
        return ()
    inspections: list[SourcePackageInspection] = []
    source_paths: dict[str, Path] = {}
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        inspection = inspect_source_package(path)
        manifest = inspection.manifest
        if manifest is not None and manifest.id in source_paths:
            inspection = SourcePackageInspection(
                inspection.path,
                None,
                f"duplicate source id {manifest.id!r}; already declared by "
                f"{source_paths[manifest.id].name}",
            )
        elif manifest is not None:
            source_paths[manifest.id] = inspection.path
        inspections.append(inspection)
    return tuple(inspections)


def package_records(directory: Path) -> tuple[dict, ...]:
    records: list[dict] = []
    for inspection in inspect_source_packages(directory):
        manifest = inspection.manifest
        records.append(
            {
                "path": str(inspection.path),
                "valid": inspection.valid,
                "error": inspection.error,
                "id": manifest.id if manifest else None,
                "name": manifest.name if manifest else None,
                "version": manifest.version if manifest else None,
                "languages": list(manifest.languages) if manifest else [],
                "domains": list(manifest.domains) if manifest else [],
                "families": list(manifest.families) if manifest else [],
                "capabilities": list(manifest.capabilities) if manifest else [],
                "permissions": (
                    {
                        "network_domains": list(manifest.network_domains),
                        "browser": manifest.browser,
                        "filesystem": "none",
                    }
                    if manifest
                    else None
                ),
                "enabled": False,
                "executable": False,
                "reason": (
                    "manifest validated; executable loading remains disabled"
                    if manifest
                    else "manifest rejected"
                ),
            }
        )
    return tuple(records)
