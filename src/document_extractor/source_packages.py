"""Read-only inspection of third-party source package manifests."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .sources import (
    BUILTIN_READER_FAMILIES,
    BUILTIN_SOURCE_CANDIDATES,
    build_default_registry,
)
from .sources.catalog import metadata_for
from .sources.declarative import DeclarativeUpdateWebSource, DeclarativeWebSource
from .sources.registry import SourceRegistry


SOURCE_PACKAGE_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_LANGUAGE = re.compile(r"^(?:[a-z]{2,3}|mul|und)$")
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_CAPABILITIES = {"url", "search", "browse", "update"}
_RUNTIME_CAPABILITIES = {"url", "update"}
_ENABLED_FILE = ".enabled"


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
        builtin_ids.update(candidate.id for candidate in BUILTIN_SOURCE_CANDIDATES)
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


def enabled_source_ids(directory: Path) -> tuple[str, ...]:
    """Read the explicit activation list without creating package state."""

    path = directory.expanduser().resolve() / _ENABLED_FILE
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source activation state must be a regular file")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("source activation state exceeds the 64 KiB limit")
    enabled: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        source_id = line.strip().casefold()
        if not source_id or source_id.startswith("#"):
            continue
        if _IDENTIFIER.fullmatch(source_id) is None:
            raise ValueError(f"invalid enabled source id: {line!r}")
        if source_id not in enabled:
            enabled.append(source_id)
    return tuple(enabled)


def _domains_overlap(first: str, second: str) -> bool:
    return (
        first == second
        or first.endswith(f".{second}")
        or second.endswith(f".{first}")
    )


def _activation_error(
    manifest: SourcePackageManifest,
    others: tuple[SourcePackageManifest, ...],
) -> str | None:
    if "url" not in manifest.capabilities:
        return "declarative activation requires the url capability"
    unsupported = sorted(set(manifest.capabilities) - _RUNTIME_CAPABILITIES)
    if unsupported:
        return (
            "declarative runtime does not implement capabilities: "
            + ", ".join(unsupported)
        )
    if not manifest.browser:
        return "declarative generic sources require browser permission"
    if any(domain not in manifest.network_domains for domain in manifest.domains):
        return "every source domain must be present in permissions.network_domains"

    builtin_domains = tuple(
        domain.casefold().rstrip(".")
        for adapter in build_default_registry().all()
        for domain in metadata_for(adapter).domains
        if domain != "*"
    ) + tuple(
        domain.casefold().rstrip(".")
        for candidate in BUILTIN_SOURCE_CANDIDATES
        for domain in candidate.domains
    )
    for domain in manifest.domains:
        if any(_domains_overlap(domain, builtin) for builtin in builtin_domains):
            return f"source domain conflicts with a built-in source: {domain}"
    for other in others:
        for domain in manifest.domains:
            if any(_domains_overlap(domain, value) for value in other.domains):
                return f"source domain conflicts with enabled package {other.id}: {domain}"
    return None


def _valid_manifests(directory: Path) -> dict[str, SourcePackageManifest]:
    return {
        inspection.manifest.id: inspection.manifest
        for inspection in inspect_source_packages(directory)
        if inspection.valid and inspection.manifest is not None
    }


def set_source_package_enabled(
    directory: Path,
    source_id: str,
    *,
    enabled: bool,
) -> tuple[str, ...]:
    """Atomically update explicit activation after validating runtime safety."""

    normalized_id = str(source_id or "").strip().casefold()
    if _IDENTIFIER.fullmatch(normalized_id) is None:
        raise ValueError("source id must use lowercase letters, numbers, and hyphens")
    root = directory.expanduser().resolve()
    manifests = _valid_manifests(root)
    current = list(enabled_source_ids(root))
    if enabled:
        if normalized_id not in manifests:
            raise ValueError(f"no valid source package found: {normalized_id}")
        others = tuple(
            manifests[item]
            for item in current
            if item != normalized_id and item in manifests
        )
        error = _activation_error(manifests[normalized_id], others)
        if error:
            raise ValueError(error)
        if normalized_id not in current:
            current.append(normalized_id)
    else:
        current = [item for item in current if item != normalized_id]

    root.mkdir(parents=True, exist_ok=True)
    state_path = root / _ENABLED_FILE
    temporary_path = root / f"{_ENABLED_FILE}.tmp"
    temporary_path.write_text(
        "".join(f"{item}\n" for item in sorted(current)),
        encoding="utf-8",
    )
    os.replace(temporary_path, state_path)
    return tuple(sorted(current))


def runtime_source_adapters(directory: Path) -> tuple[DeclarativeWebSource, ...]:
    """Build enabled code-free adapters, failing closed on stale state."""

    manifests = _valid_manifests(directory)
    enabled = enabled_source_ids(directory)
    missing = sorted(set(enabled) - set(manifests))
    if missing:
        raise ValueError(
            "enabled source package is missing or invalid: " + ", ".join(missing)
        )
    adapters: list[DeclarativeWebSource] = []
    active_manifests: list[SourcePackageManifest] = []
    for source_id in enabled:
        manifest = manifests[source_id]
        error = _activation_error(manifest, tuple(active_manifests))
        if error:
            raise ValueError(f"cannot activate source package {source_id}: {error}")
        adapter_type = (
            DeclarativeUpdateWebSource
            if "update" in manifest.capabilities
            else DeclarativeWebSource
        )
        adapters.append(
            adapter_type(
                source_id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                languages=manifest.languages,
                domains=manifest.domains,
                network_domains=manifest.network_domains,
                families=manifest.families,
            )
        )
        active_manifests.append(manifest)
    return tuple(adapters)


def build_runtime_registry(directory: Path | None = None) -> SourceRegistry:
    registry = build_default_registry()
    root = directory or default_source_packages_dir()
    for adapter in runtime_source_adapters(root):
        registry.register(adapter)
    return registry


def package_records(directory: Path) -> tuple[dict, ...]:
    enabled_ids = set(enabled_source_ids(directory))
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
                "enabled": bool(manifest and manifest.id in enabled_ids),
                "executable": False,
                "reason": (
                    "enabled as a code-free declarative generic source"
                    if manifest and manifest.id in enabled_ids
                    else "manifest validated; explicit activation is required"
                    if manifest
                    else "manifest rejected"
                ),
            }
        )
    return tuple(records)
