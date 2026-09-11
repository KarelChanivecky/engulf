from __future__ import annotations

import hashlib
import heapq
import importlib.util
import itertools
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib.metadata import Distribution, EntryPoint, entry_points
from pathlib import Path
from types import ModuleType

from engulf_api import (
    PLUGIN_API_MAJOR,
    DependencyPosition,
    ElevationRequirement,
    GoalContract,
    GoalRequirement,
    Plugin,
    PluginDependency,
    PluginMetadata,
    plugin_name,
    validate_global_identifier,
)

from ._plugin_execution import _InProcessPluginEndpoint, _PluginEndpoint
from .plugin_info import (
    ActivePlugin,
    PluginSource,
    PluginSourceKind,
    _normalize_distribution_name,
)


class PluginLoadError(RuntimeError):
    """Raised when a plugin directory or plugin module cannot be loaded."""


class PluginDependencyError(PluginLoadError):
    """Raised when plugin metadata cannot produce valid activation orders."""


class PluginElevationError(PluginLoadError):
    """Raised when an active plugin requires unavailable elevation."""


class PluginRequirementError(PluginLoadError):
    """Raised when an application-required plugin is unavailable."""


@dataclass(frozen=True, slots=True)
class DistributionIdentity:
    """Distribution identity cached for entry-point provenance comparisons."""

    present: bool
    name: str | None
    version: str | None
    normalized_name: str


_MISSING_DISTRIBUTION_IDENTITY = DistributionIdentity(False, None, None, "")


class EntryPointIndex:
    """One installed entry-point snapshot shared by an application construction."""

    __slots__ = (
        "_distribution_files",
        "_distribution_identities",
        "_groups",
        "_prefixes",
        "_requirements",
    )

    def __init__(
        self,
        groups: dict[str, tuple[EntryPoint, ...]],
        prefixes: Iterable[str] = (),
    ) -> None:
        self._groups = dict(groups)
        self._prefixes = tuple(dict.fromkeys(prefixes))
        self._distribution_identities: dict[
            int, tuple[Distribution, DistributionIdentity]
        ] = {}
        self._distribution_files: dict[
            int, tuple[Distribution, frozenset[Path] | None]
        ] = {}
        self._requirements: dict[int, frozenset[str]] = {}

    @classmethod
    def discover(
        cls,
        groups: Iterable[str],
        prefixes: Iterable[str] = (),
    ) -> EntryPointIndex:
        if isinstance(groups, str):
            raise TypeError("entry-point groups must be an iterable, not a string")
        if isinstance(prefixes, str):
            raise TypeError("entry-point prefixes must be an iterable, not a string")
        requested = tuple(dict.fromkeys(groups))
        requested_prefixes = tuple(dict.fromkeys(prefixes))
        if any(not isinstance(group, str) or not group for group in requested):
            raise ValueError("entry-point groups must be nonempty strings")
        if any(
            not isinstance(prefix, str) or not prefix for prefix in requested_prefixes
        ):
            raise ValueError("entry-point prefixes must be nonempty strings")
        try:
            discovered = entry_points()
        except Exception as error:
            raise PluginLoadError(
                "failed to discover installed entry points"
            ) from error
        selected: dict[str, list[EntryPoint]] = {group: [] for group in requested}
        for entry_point in discovered:
            group_entries = selected.get(entry_point.group)
            if group_entries is None and any(
                entry_point.group.startswith(prefix) for prefix in requested_prefixes
            ):
                group_entries = selected.setdefault(entry_point.group, [])
            if group_entries is not None:
                group_entries.append(entry_point)
        return cls(
            {group: tuple(group_entries) for group, group_entries in selected.items()},
            requested_prefixes,
        )

    def entries(self, group: str) -> tuple[EntryPoint, ...]:
        try:
            return self._groups[group]
        except KeyError as error:
            if any(group.startswith(prefix) for prefix in self._prefixes):
                return ()
            raise ValueError(f"entry-point group was not indexed: {group!r}") from error

    def distribution_requirements(
        self,
        entry_point: EntryPoint,
    ) -> frozenset[str] | None:
        """Return normalized required distribution names, or None when unknown."""
        distribution = entry_point.dist
        if distribution is None:
            return None
        key = id(distribution)
        cached = self._requirements.get(key)
        if cached is not None:
            return cached
        try:
            requires = distribution.requires or ()
        except Exception:  # noqa: BLE001 - unreadable metadata is not fatal.
            requires = ()
        names = frozenset(
            _normalize_distribution_name(name)
            for name in (_requirement_name(item) for item in requires)
            if name
        )
        self._requirements[key] = names
        return names

    def distribution_identity(self, entry_point: EntryPoint) -> DistributionIdentity:
        distribution = entry_point.dist
        if distribution is None:
            return _MISSING_DISTRIBUTION_IDENTITY
        key = id(distribution)
        cached = self._distribution_identities.get(key)
        if cached is not None:
            cached_distribution, identity = cached
            if cached_distribution is not distribution:
                raise AssertionError("entry-point distribution identity collision")
            return identity
        name = distribution.name
        version = distribution.version
        identity = DistributionIdentity(
            True,
            name,
            version,
            _normalize_distribution_name(name or ""),
        )
        self._distribution_identities[key] = (distribution, identity)
        return identity

    def distribution_owns_path(self, entry_point: EntryPoint, path: Path) -> bool:
        """Return whether installed file records verifiably contain ``path``."""
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("path must be an absolute pathlib.Path")
        distribution = entry_point.dist
        if distribution is None:
            return False
        key = id(distribution)
        cached = self._distribution_files.get(key)
        if cached is not None:
            cached_distribution, files = cached
            if cached_distribution is not distribution:
                raise AssertionError("entry-point distribution identity collision")
            return files is not None and path in files

        resolved: frozenset[Path] | None = None
        try:
            records = distribution.files
            if records is not None:
                owned: set[Path] = set()
                for record in records:
                    try:
                        owned.add(
                            Path(str(distribution.locate_file(record))).resolve(
                                strict=True
                            )
                        )
                    except OSError, RuntimeError, TypeError, ValueError:
                        continue
                resolved = frozenset(owned)
        except Exception:  # noqa: BLE001 - unreadable metadata denies ownership.
            resolved = None
        self._distribution_files[key] = (distribution, resolved)
        return resolved is not None and path in resolved


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """Validated, immutable metadata for one discovered plugin."""

    metadata: PluginMetadata
    source: PluginSource
    endpoint: _PluginEndpoint
    discovery_index: int

    @property
    def active_plugin(self) -> ActivePlugin:
        return ActivePlugin(metadata=self.metadata, source=self.source)

    @property
    def plugin_id(self) -> str:
        return self.metadata.plugin_id

    @property
    def goal_requirement(self) -> GoalRequirement:
        return self.metadata.goal_requirement

    @property
    def priority(self) -> int:
        return self.metadata.priority

    @property
    def elevation_requirement(self) -> ElevationRequirement:
        return self.metadata.elevation_requirement

    @property
    def dependencies(self) -> tuple[PluginDependency, ...]:
        return self.metadata.plugin_dependencies

    @property
    def context_reads(self) -> frozenset[str]:
        return self.metadata.context_reads

    @property
    def context_writes(self) -> frozenset[str]:
        return self.metadata.context_writes


@dataclass(frozen=True, slots=True)
class PluginOrders:
    """Independent activation orders for the two call phases."""

    preprocess: tuple[LoadedPlugin, ...]
    postprocess: tuple[LoadedPlugin, ...]


class PluginPolicyMode(StrEnum):
    """Application policy used to turn catalog candidates into active plugins."""

    DECLARED = "declared"
    ALLOWLIST = "allowlist"
    BLOCKLIST = "blocklist"


@dataclass(frozen=True, slots=True)
class PluginPolicy:
    """Immutable application-side plugin activation policy."""

    mode: PluginPolicyMode = PluginPolicyMode.DECLARED
    plugin_ids: frozenset[str] = frozenset()
    include_dependencies: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.mode, PluginPolicyMode):
            raise TypeError("plugin policy mode must be a PluginPolicyMode")
        if type(self.plugin_ids) is not frozenset:
            raise TypeError("plugin policy IDs must be a frozenset")
        if type(self.include_dependencies) is not bool:
            raise TypeError("include_dependencies must be a boolean")
        if self.include_dependencies and self.mode is not PluginPolicyMode.ALLOWLIST:
            raise ValueError(
                "include_dependencies is supported only by allowlist policy"
            )
        for plugin_id in self.plugin_ids:
            validate_global_identifier(plugin_id, label="plugin policy ID")

    @classmethod
    def declared(cls, *, include: Iterable[str] = ()) -> PluginPolicy:
        return cls(PluginPolicyMode.DECLARED, _policy_ids(include))

    @classmethod
    def allow_only(
        cls,
        plugin_ids: Iterable[str],
        *,
        include_dependencies: bool = False,
    ) -> PluginPolicy:
        return cls(
            PluginPolicyMode.ALLOWLIST,
            _policy_ids(plugin_ids),
            include_dependencies,
        )

    @classmethod
    def allow_all_except(cls, plugin_ids: Iterable[str]) -> PluginPolicy:
        return cls(PluginPolicyMode.BLOCKLIST, _policy_ids(plugin_ids))

    def including(self, plugin_ids: Iterable[str]) -> PluginPolicy:
        """Return a policy that additionally selects the supplied plugin IDs."""
        additions = _policy_ids(plugin_ids)
        if self.mode is PluginPolicyMode.BLOCKLIST:
            selected_ids = self.plugin_ids - additions
        else:
            selected_ids = self.plugin_ids | additions
        return replace(self, plugin_ids=selected_ids)


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginDiscovery:
    missing_policy_ids: tuple[str, ...]
    loaded_plugins: tuple[LoadedPlugin, ...]
    packaging_warnings: tuple[str, ...] = ()

    def close(self) -> None:
        """Release every materialized endpoint after abandoned discovery."""
        _close_plugin_endpoints(self.loaded_plugins)


_NO_POSITION = "none"
_DEPENDENCY_FIELDS = ("preprocess", "postprocess")
_DEPENDENCY_EXAMPLE = "'preprocess=before; postprocess=after'"
_requirement_name_pattern = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_namespace_counter = itertools.count()
_missing = object()
_application_id_pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def normalize_application_id(application_id: str) -> str:
    """Return a canonical distribution-style application identifier."""
    if not isinstance(application_id, str):
        raise TypeError("application_id must be a string")
    if not _application_id_pattern.fullmatch(application_id):
        raise ValueError(
            "application_id must contain only letters, numbers, '.', '_' or '-', "
            "and must begin and end with a letter or number"
        )
    return re.sub(r"[-_.]+", "-", application_id).lower()


def normalize_plugin_declaration_application_ids(
    application_id: str,
    inherited_application_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return the current and inherited declaration identities in stable order."""
    if isinstance(inherited_application_ids, str):
        raise TypeError(
            "plugin declaration application IDs must be an iterable, not a string"
        )
    try:
        inherited = tuple(inherited_application_ids)
    except TypeError as error:
        raise TypeError(
            "plugin declaration application IDs must be iterable strings"
        ) from error

    result: list[str] = []
    seen: set[str] = set()
    for value in (application_id, *inherited):
        normalized = normalize_application_id(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def application_plugin_entry_point_group(application_id: str) -> str:
    """Return the plugin-side activation declaration group for an application."""
    normalized = normalize_application_id(application_id).replace("-", "_")
    return f"engulf.plugins.v{PLUGIN_API_MAJOR}.application.{normalized}"


def goal_plugin_entry_point_group(
    goal_id: str,
    goal_api_major: int,
) -> str:
    """Return the metadata catalog for one exact goal contract."""
    validated = validate_global_identifier(goal_id, label="goal_id")
    if type(goal_api_major) is not int or goal_api_major < 1:
        raise ValueError("goal API major must be a positive integer")
    normalized = re.sub(r"[-_.]+", "_", validated)
    return f"engulf.plugins.v{PLUGIN_API_MAJOR}.goal.v{goal_api_major}.{normalized}"


def plugin_dependency_entry_point_group(plugin_id: str) -> str:
    """Return the group where one plugin declares its plugin dependencies."""
    validated = validate_global_identifier(plugin_id, label="plugin_id")
    normalized = re.sub(r"[-_.]+", "_", validated)
    return f"engulf.plugins.v{PLUGIN_API_MAJOR}.dependency.{normalized}"


def plugin_dependency_entry_point_prefix() -> str:
    """Return the shared prefix of every plugin-dependency entry-point group."""
    return f"engulf.plugins.v{PLUGIN_API_MAJOR}.dependency."


def parse_plugin_dependency(plugin_id: str, declaration: str) -> PluginDependency:
    """Build one dependency from an entry-point name and its declared fields."""
    if not isinstance(declaration, str):
        raise PluginDependencyError("dependency declaration must be a string")
    fields = _dependency_fields(plugin_id, declaration)
    positions: list[DependencyPosition | None] = []
    for name in _DEPENDENCY_FIELDS:
        if name not in fields:
            raise PluginDependencyError(
                f"dependency on {plugin_id!r} must declare {name!r}; expected "
                f"{_DEPENDENCY_EXAMPLE}"
            )
        value = fields[name]
        if value == _NO_POSITION:
            positions.append(None)
            continue
        try:
            positions.append(DependencyPosition(value))
        except ValueError as error:
            raise PluginDependencyError(
                f"{name} position for dependency on {plugin_id!r} must be "
                f"'before', 'after', or '{_NO_POSITION}', not {value!r}"
            ) from error
    try:
        return PluginDependency(plugin_id, positions[0], positions[1])
    except (TypeError, ValueError) as error:
        raise PluginDependencyError(str(error)) from error


def _dependency_fields(plugin_id: str, declaration: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in declaration.split(";"):
        field = part.strip()
        if not field:
            continue
        name, separator, value = field.partition("=")
        name = name.strip()
        if not separator:
            raise PluginDependencyError(
                f"dependency on {plugin_id!r} must declare ';'-separated "
                f"'<field>=<value>' pairs, not {field!r}; expected "
                f"{_DEPENDENCY_EXAMPLE}"
            )
        if name not in _DEPENDENCY_FIELDS:
            raise PluginDependencyError(
                f"dependency on {plugin_id!r} declares unknown field {name!r}; "
                f"expected {' and '.join(repr(item) for item in _DEPENDENCY_FIELDS)}"
            )
        if name in fields:
            raise PluginDependencyError(
                f"dependency on {plugin_id!r} declares {name!r} more than once"
            )
        fields[name] = value.strip()
    return fields


def resolve_plugin_directory(plugin_dir: str | os.PathLike[str]) -> Path:
    """Validate and resolve a plugin directory path."""
    try:
        raw_path = os.fspath(plugin_dir)
    except TypeError as error:
        raise PluginLoadError("plugin directory must be a path-like value") from error

    if isinstance(raw_path, bytes):
        raise PluginLoadError("plugin directory must be a text path")
    if not raw_path:
        raise PluginLoadError("plugin directory cannot be empty")

    directory = Path(raw_path).expanduser().resolve()
    if not directory.exists():
        raise PluginLoadError(f"plugin directory does not exist: {directory}")
    if not directory.is_dir():
        raise PluginLoadError(f"plugin directory is not a directory: {directory}")
    return directory


def load_directory_plugins(plugin_dir: str | os.PathLike[str]) -> tuple[Plugin, ...]:
    """Import plugins from a directory in lexical filename order.

    Each non-private, immediate ``*.py`` file must export ``plugin`` as either a
    Plugin instance or a zero-argument callable returning one. Private modules
    remain importable as helpers through relative imports.
    """
    directory = resolve_plugin_directory(plugin_dir)
    module_paths = sorted(
        path for path in directory.glob("*.py") if not path.name.startswith("_")
    )

    for path in module_paths:
        if not path.stem.isidentifier():
            raise PluginLoadError(
                f"plugin filename must have a valid Python identifier: {path.name}"
            )

    digest = hashlib.sha256(os.fsencode(directory)).hexdigest()[:16]
    namespace = f"_engulf_plugins_{digest}_{next(_namespace_counter)}"
    package = ModuleType(namespace)
    package.__package__ = namespace
    package.__path__ = [str(directory)]
    package.__spec__ = importlib.util.spec_from_loader(
        namespace, loader=None, is_package=True
    )
    sys.modules[namespace] = package

    try:
        plugins = tuple(_load_plugin(path, namespace) for path in module_paths)
    except Exception:
        _remove_namespace(namespace)
        raise

    return plugins


def load_installed_plugins(
    application_id: str,
    contract: GoalContract,
    policy: PluginPolicy,
    *,
    plugin_declaration_application_ids: Iterable[str] = (),
) -> PluginDiscovery:
    """Select installed plugins without any directory-plugin candidates."""
    return discover_plugins(
        application_id,
        contract,
        policy,
        directory_plugins=(),
        plugin_declaration_application_ids=plugin_declaration_application_ids,
        discover_installed=True,
    )


def discover_plugins(
    application_id: str,
    contract: GoalContract,
    policy: PluginPolicy,
    *,
    directory_plugins: Iterable[Plugin],
    plugin_directory: Path | None = None,
    plugin_declaration_application_ids: Iterable[str] = (),
    discover_installed: bool,
    entry_point_index: EntryPointIndex | None = None,
) -> PluginDiscovery:
    """Select compatible directory and installed plugins for one application."""
    if not isinstance(contract, GoalContract):
        raise TypeError("contract must be a GoalContract")
    if not isinstance(policy, PluginPolicy):
        raise TypeError("policy must be a PluginPolicy")
    if not isinstance(discover_installed, bool):
        raise TypeError("discover_installed must be a boolean")
    if entry_point_index is not None and not isinstance(
        entry_point_index, EntryPointIndex
    ):
        raise TypeError("entry_point_index must be an EntryPointIndex or None")
    if plugin_directory is not None and (
        not isinstance(plugin_directory, Path) or not plugin_directory.is_absolute()
    ):
        raise ValueError("plugin_directory must be an absolute pathlib.Path or None")
    declaration_application_ids = normalize_plugin_declaration_application_ids(
        application_id,
        plugin_declaration_application_ids,
    )

    local_plugins = tuple(directory_plugins)
    sources: dict[int, PluginSource] = {
        id(plugin): _directory_plugin_source(plugin, plugin_directory)
        for plugin in local_plugins
    }
    local_by_id: dict[str, list[Plugin]] = {}
    for plugin in local_plugins:
        _validate_goal_compatibility(
            plugin,
            contract,
            source="directory plugin",
        )
        try:
            plugin_id = validate_global_identifier(
                plugin.plugin_id,
                label="directory plugin_id",
            )
        except (TypeError, ValueError) as error:
            raise PluginDependencyError(str(error)) from error
        local_by_id.setdefault(plugin_id, []).append(plugin)

    catalog_entries: dict[str, EntryPoint] = {}
    application_entry_catalogs: list[dict[str, EntryPoint]] = []
    if discover_installed:
        catalog_group = goal_plugin_entry_point_group(
            contract.goal_id,
            contract.api_major,
        )
        application_groups = tuple(
            application_plugin_entry_point_group(declaration_application_id)
            for declaration_application_id in declaration_application_ids
        )
        if entry_point_index is None:
            entry_point_index = EntryPointIndex.discover(
                (catalog_group, *application_groups),
                (plugin_dependency_entry_point_prefix(),),
            )
        catalog_entries = _entry_point_catalog(catalog_group, entry_point_index)
        application_entry_catalogs = [
            _entry_point_catalog(group, entry_point_index)
            for group in application_groups
        ]
    if entry_point_index is None:
        entry_point_index = EntryPointIndex(
            {},
            (plugin_dependency_entry_point_prefix(),),
        )
    dependencies_by_id = _collect_plugin_dependencies(
        catalog_entries,
        entry_point_index,
    )
    packaging_warnings = _packaging_bridge_warnings(
        catalog_entries,
        dependencies_by_id,
        entry_point_index,
    )

    declared_ids: set[str] = set()
    for application_entries in application_entry_catalogs:
        for plugin_id, declaration in application_entries.items():
            catalog = catalog_entries.get(plugin_id)
            if catalog is None:
                continue
            if not _same_entry_point_source(
                declaration,
                catalog,
                entry_point_index,
            ):
                raise PluginLoadError(
                    f"application declaration for plugin {plugin_id!r} does not "
                    "match its goal catalog entry"
                )
            declared_ids.add(plugin_id)

    if policy.mode is PluginPolicyMode.DECLARED:
        selected_local_ids = set(local_by_id)
        selected_catalog_ids = declared_ids | set(policy.plugin_ids)
    elif policy.mode is PluginPolicyMode.ALLOWLIST:
        selected_local_ids = set(policy.plugin_ids) & set(local_by_id)
        selected_catalog_ids = set(policy.plugin_ids) & set(catalog_entries)
    else:
        selected_local_ids = set(local_by_id) - set(policy.plugin_ids)
        selected_catalog_ids = set(catalog_entries) - set(policy.plugin_ids)

    if policy.include_dependencies:
        _expand_allowlist_dependencies(
            local_by_id,
            catalog_entries,
            dependencies_by_id,
            selected_local_ids,
            selected_catalog_ids,
        )

    installed_plugins: list[Plugin] = []
    selected_entries = (
        catalog_entries[plugin_id]
        for plugin_id in selected_catalog_ids
        if plugin_id in catalog_entries
    )
    for entry_point in sorted(
        selected_entries,
        key=lambda item: _entry_point_sort_key(item, entry_point_index),
    ):
        installed_plugin = _load_catalog_plugin(
            entry_point,
            contract,
            entry_point_index,
        )
        sources[id(installed_plugin)] = _installed_plugin_source(
            entry_point,
            entry_point_index,
        )
        installed_plugins.append(installed_plugin)

    selected_local = tuple(
        plugin for plugin in local_plugins if plugin.plugin_id in selected_local_ids
    )
    available_ids = set(local_by_id) | set(catalog_entries)
    missing = (
        ()
        if policy.mode is PluginPolicyMode.BLOCKLIST
        else tuple(sorted(set(policy.plugin_ids) - available_ids))
    )
    selected_plugins = selected_local + tuple(installed_plugins)
    loaded_plugins: list[LoadedPlugin] = []
    try:
        for discovery_index, plugin in enumerate(selected_plugins):
            loaded_plugins.append(
                _snapshot_plugin(
                    plugin,
                    discovery_index,
                    source=sources[id(plugin)],
                    dependencies=dependencies_by_id.get(plugin.plugin_id, ()),
                )
            )
    except BaseException as discovery_error:
        _cleanup_discovery_failure(discovery_error, loaded_plugins)
        raise
    return PluginDiscovery(
        missing_policy_ids=missing,
        loaded_plugins=tuple(loaded_plugins),
        packaging_warnings=packaging_warnings,
    )


def _expand_allowlist_dependencies(
    local_by_id: dict[str, list[Plugin]],
    catalog_entries: dict[str, EntryPoint],
    dependencies_by_id: dict[str, tuple[PluginDependency, ...]],
    selected_local_ids: set[str],
    selected_catalog_ids: set[str],
) -> None:
    """Activate reachable dependencies from packaging metadata, importing nothing."""
    pending = list(selected_local_ids | selected_catalog_ids)
    heapq.heapify(pending)
    expanded: set[str] = set()

    while pending:
        plugin_id = heapq.heappop(pending)
        if plugin_id in expanded:
            continue
        expanded.add(plugin_id)
        if plugin_id in local_by_id:
            selected_local_ids.add(plugin_id)
        if plugin_id in catalog_entries:
            selected_catalog_ids.add(plugin_id)
        for dependency in dependencies_by_id.get(plugin_id, ()):
            if dependency.plugin_id not in expanded:
                heapq.heappush(pending, dependency.plugin_id)


def _load_catalog_plugin(
    entry_point: EntryPoint,
    contract: GoalContract,
    entry_point_index: EntryPointIndex,
) -> Plugin:
    identifier = _entry_point_identifier(entry_point, entry_point_index)
    plugin = _load_entry_point(entry_point, identifier)
    if plugin.plugin_id != entry_point.name:
        raise PluginLoadError(
            f"installed plugin {identifier} exports plugin_id "
            f"{plugin.plugin_id!r}; entry-point names must equal plugin_id"
        )
    _validate_goal_compatibility(plugin, contract, source=identifier)
    return plugin


def resolve_plugin_orders(plugins: Iterable[Plugin]) -> PluginOrders:
    """Validate plugin metadata and resolve deterministic per-phase orders."""
    loaded = tuple(
        _snapshot_plugin(
            plugin,
            discovery_index,
            source=_directory_plugin_source(plugin, None),
        )
        for discovery_index, plugin in enumerate(plugins)
    )
    return _resolve_loaded_plugin_orders(loaded)


def resolve_discovered_plugin_orders(discovery: PluginDiscovery) -> PluginOrders:
    """Resolve orders from metadata snapshotted during plugin discovery."""
    if not isinstance(discovery, PluginDiscovery):
        raise TypeError("discovery must be a PluginDiscovery")
    return _resolve_loaded_plugin_orders(discovery.loaded_plugins)


def _close_plugin_endpoints(plugins: Iterable[LoadedPlugin]) -> None:
    failures: list[Exception] = []
    closed: set[int] = set()
    for item in plugins:
        identity = id(item.endpoint)
        if identity in closed:
            continue
        closed.add(identity)
        try:
            item.endpoint.close()
        except Exception as error:  # noqa: BLE001 - endpoints are extensible.
            failures.append(error)
    if failures:
        raise ExceptionGroup("plugin endpoint cleanup failed", failures)


def _cleanup_discovery_failure(
    discovery_error: BaseException,
    plugins: Iterable[LoadedPlugin],
) -> None:
    try:
        _close_plugin_endpoints(plugins)
    except Exception as cleanup_error:  # noqa: BLE001 - preserve both failures.
        raise BaseExceptionGroup(
            "plugin discovery and endpoint cleanup failed",
            (discovery_error, cleanup_error),
        ) from None


def validate_plugin_elevation(
    plugins: Iterable[LoadedPlugin],
    *,
    elevated: bool,
) -> None:
    """Require elevation when any selected plugin declares it mandatory."""
    if type(elevated) is not bool:
        raise TypeError("elevated must be a boolean")
    required = tuple(
        item.plugin_id
        for item in plugins
        if item.elevation_requirement is ElevationRequirement.REQUIRED
    )
    if required and not elevated:
        raise PluginElevationError(
            "process elevation is required by active plugins: "
            + ", ".join(repr(plugin_id) for plugin_id in required)
        )


def _resolve_loaded_plugin_orders(
    loaded: tuple[LoadedPlugin, ...],
) -> PluginOrders:
    by_id: dict[str, LoadedPlugin] = {}
    for item in loaded:
        existing = by_id.get(item.plugin_id)
        if existing is not None:
            raise PluginDependencyError(
                f"duplicate plugin_id {item.plugin_id!r}: "
                f"{existing.endpoint.implementation_name} and "
                f"{item.endpoint.implementation_name}"
            )
        by_id[item.plugin_id] = item

    for item in loaded:
        dependency_ids: set[str] = set()
        for dependency in item.dependencies:
            if dependency.plugin_id in dependency_ids:
                raise PluginDependencyError(
                    f"plugin {item.plugin_id!r} declares dependency "
                    f"{dependency.plugin_id!r} more than once"
                )
            dependency_ids.add(dependency.plugin_id)
            if dependency.plugin_id == item.plugin_id:
                raise PluginDependencyError(
                    f"plugin {item.plugin_id!r} cannot depend on itself"
                )
            if dependency.plugin_id not in by_id:
                raise PluginDependencyError(
                    f"plugin {item.plugin_id!r} requires missing plugin "
                    f"{dependency.plugin_id!r}"
                )

    return PluginOrders(
        preprocess=_topological_order(loaded, "preprocess"),
        postprocess=_topological_order(loaded, "postprocess"),
    )


def _load_plugin(path: Path, namespace: str) -> Plugin:
    module_name = f"{namespace}.{path.stem}"
    module = sys.modules.get(module_name)

    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"could not create an import spec for plugin: {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            raise PluginLoadError(f"failed to import plugin module: {path}") from error

    exported = getattr(module, "plugin", _missing)
    if exported is _missing:
        raise PluginLoadError(f"plugin module does not export 'plugin': {path}")

    return _materialize_plugin(exported, f"plugin module {path}")


def _load_entry_point(entry_point: EntryPoint, identifier: str) -> Plugin:
    try:
        exported = entry_point.load()
    except Exception as error:
        raise PluginLoadError(
            f"failed to load installed plugin {identifier} from {entry_point.value!r}"
        ) from error
    return _materialize_plugin(exported, f"installed plugin {identifier}")


def _materialize_plugin(exported: object, source: str) -> Plugin:

    if isinstance(exported, Plugin):
        return exported

    if not callable(exported):
        raise PluginLoadError(f"{source} must export a Plugin or zero-argument factory")

    try:
        plugin = exported()
    except Exception as error:
        raise PluginLoadError(f"plugin factory failed for {source}") from error

    if not isinstance(plugin, Plugin):
        raise PluginLoadError(f"plugin factory did not return a Plugin for {source}")
    return plugin


def _snapshot_plugin(
    plugin: Plugin,
    discovery_index: int,
    *,
    source: PluginSource,
    dependencies: tuple[PluginDependency, ...] = (),
) -> LoadedPlugin:
    name = plugin_name(plugin)
    if getattr(plugin, "plugin_dependencies", None):
        raise PluginDependencyError(
            f"plugin {name} declares plugin_dependencies in code; declare plugin "
            "dependencies in the engulf.plugins.v1.dependency.<plugin_id> "
            "entry-point group of its distribution instead"
        )
    try:
        metadata = plugin.metadata
    except Exception as error:
        raise PluginDependencyError(
            f"invalid metadata for plugin {name}: {error}"
        ) from error
    if not isinstance(metadata, PluginMetadata):
        raise PluginDependencyError(
            f"metadata for plugin {name} must be a PluginMetadata"
        )
    if dependencies:
        metadata = replace(metadata, plugin_dependencies=dependencies)
    return LoadedPlugin(
        metadata=metadata,
        source=source,
        endpoint=_InProcessPluginEndpoint(plugin),
        discovery_index=discovery_index,
    )


def _topological_order(
    plugins: tuple[LoadedPlugin, ...], phase: str
) -> tuple[LoadedPlugin, ...]:
    by_id = {item.plugin_id: item for item in plugins}
    adjacency: dict[str, set[str]] = {item.plugin_id: set() for item in plugins}
    indegree = {item.plugin_id: 0 for item in plugins}

    for item in plugins:
        for dependency in item.dependencies:
            position = getattr(dependency, phase)
            if position is None:
                continue
            if position is DependencyPosition.BEFORE:
                source, target = dependency.plugin_id, item.plugin_id
            else:
                source, target = item.plugin_id, dependency.plugin_id
            if target not in adjacency[source]:
                adjacency[source].add(target)
                indegree[target] += 1

    ready = [
        (-item.priority, item.discovery_index, item.plugin_id)
        for item in plugins
        if indegree[item.plugin_id] == 0
    ]
    heapq.heapify(ready)
    ordered: list[LoadedPlugin] = []

    while ready:
        _, _, plugin_id = heapq.heappop(ready)
        ordered.append(by_id[plugin_id])
        for target in sorted(
            adjacency[plugin_id], key=lambda value: by_id[value].discovery_index
        ):
            indegree[target] -= 1
            if indegree[target] == 0:
                item = by_id[target]
                heapq.heappush(
                    ready, (-item.priority, item.discovery_index, item.plugin_id)
                )

    if len(ordered) != len(plugins):
        remaining = {plugin_id for plugin_id, degree in indegree.items() if degree > 0}
        cycle = _find_cycle(adjacency, by_id, remaining)
        raise PluginDependencyError(
            f"{phase} plugin dependency cycle: {' -> '.join(cycle)}"
        )
    return tuple(ordered)


def _find_cycle(
    adjacency: dict[str, set[str]],
    by_id: dict[str, LoadedPlugin],
    remaining: set[str],
) -> tuple[str, ...]:
    state: dict[str, int] = {}
    stack: list[str] = []
    stack_positions: dict[str, int] = {}

    def visit(plugin_id: str) -> tuple[str, ...] | None:
        state[plugin_id] = 1
        stack_positions[plugin_id] = len(stack)
        stack.append(plugin_id)
        neighbors = sorted(
            (target for target in adjacency[plugin_id] if target in remaining),
            key=lambda value: by_id[value].discovery_index,
        )
        for target in neighbors:
            if state.get(target, 0) == 0:
                cycle = visit(target)
                if cycle is not None:
                    return cycle
            elif state[target] == 1:
                return tuple(stack[stack_positions[target] :] + [target])
        stack.pop()
        stack_positions.pop(plugin_id)
        state[plugin_id] = 2
        return None

    for plugin_id in sorted(remaining, key=lambda value: by_id[value].discovery_index):
        if state.get(plugin_id, 0) == 0:
            cycle = visit(plugin_id)
            if cycle is not None:
                return cycle
    raise AssertionError("cyclic graph did not contain a discoverable cycle")


def _requirement_name(requirement: str) -> str:
    match = _requirement_name_pattern.match(requirement)
    return "" if match is None else match.group(1)


def _entry_point_sort_key(
    entry_point: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> tuple[str, str, str]:
    distribution_name = _entry_point_distribution_name(
        entry_point,
        entry_point_index,
    )
    return distribution_name.casefold(), entry_point.name, entry_point.value


def _directory_plugin_source(
    plugin: Plugin,
    directory: Path | None,
) -> PluginSource:
    if directory is None:
        return PluginSource(
            kind=PluginSourceKind.DIRECT,
            target=plugin_name(plugin),
        )
    return PluginSource(
        kind=PluginSourceKind.DIRECTORY,
        target=plugin_name(plugin),
        directory=directory,
    )


def _installed_plugin_source(
    entry_point: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> PluginSource:
    distribution = entry_point_index.distribution_identity(entry_point)
    return PluginSource(
        kind=PluginSourceKind.INSTALLED,
        target=entry_point.value,
        distribution_name=distribution.name or None,
        distribution_version=distribution.version or None,
        entry_point_group=entry_point.group,
        entry_point_value=entry_point.value,
    )


def _entry_point_identifier(
    entry_point: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> str:
    distribution = entry_point_index.distribution_identity(entry_point)
    distribution_name = distribution.name or "unknown-distribution"
    version = distribution.version or "unknown"
    return f"{distribution_name} {version}:{entry_point.name}"


def _entry_point_distribution_name(
    entry_point: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> str:
    return (
        entry_point_index.distribution_identity(entry_point).name
        or "unknown-distribution"
    )


def _entry_point_catalog(
    group: str,
    entry_point_index: EntryPointIndex,
) -> dict[str, EntryPoint]:
    catalog: dict[str, EntryPoint] = {}
    for entry_point in sorted(
        entry_point_index.entries(group),
        key=lambda item: _entry_point_sort_key(item, entry_point_index),
    ):
        try:
            plugin_id = validate_global_identifier(
                entry_point.name,
                label=f"entry-point name in {group!r}",
            )
        except (TypeError, ValueError) as error:
            raise PluginLoadError(str(error)) from error
        existing = catalog.get(plugin_id)
        if existing is not None:
            raise PluginLoadError(
                f"duplicate plugin ID {plugin_id!r} in entry-point group {group!r}: "
                f"{_entry_point_identifier(existing, entry_point_index)} and "
                f"{_entry_point_identifier(entry_point, entry_point_index)}"
            )
        catalog[plugin_id] = entry_point
    return catalog


def _same_entry_point_source(
    left: EntryPoint,
    right: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> bool:
    if left.value != right.value:
        return False
    return _same_distribution(left, right, entry_point_index)


def _same_distribution(
    left: EntryPoint,
    right: EntryPoint,
    entry_point_index: EntryPointIndex,
) -> bool:
    left_distribution = entry_point_index.distribution_identity(left)
    right_distribution = entry_point_index.distribution_identity(right)
    if not left_distribution.present or not right_distribution.present:
        return left_distribution.present is right_distribution.present
    return (
        left_distribution.normalized_name == right_distribution.normalized_name
        and left_distribution.version == right_distribution.version
    )


def _collect_plugin_dependencies(
    catalog_entries: dict[str, EntryPoint],
    entry_point_index: EntryPointIndex,
) -> dict[str, tuple[PluginDependency, ...]]:
    """Read every cataloged plugin's dependencies from its packaging metadata."""
    collected: dict[str, tuple[PluginDependency, ...]] = {}
    for plugin_id, catalog in catalog_entries.items():
        group = plugin_dependency_entry_point_group(plugin_id)
        dependencies: list[PluginDependency] = []
        seen: set[str] = set()
        for entry_point in sorted(
            entry_point_index.entries(group),
            key=lambda item: _entry_point_sort_key(item, entry_point_index),
        ):
            if not _same_distribution(entry_point, catalog, entry_point_index):
                raise PluginLoadError(
                    f"plugin dependency declaration {entry_point.name!r} in group "
                    f"{group!r} does not come from the distribution providing "
                    f"plugin {plugin_id!r}"
                )
            try:
                dependency_id = validate_global_identifier(
                    entry_point.name,
                    label=f"entry-point name in {group!r}",
                )
            except (TypeError, ValueError) as error:
                raise PluginDependencyError(str(error)) from error
            if dependency_id in seen:
                raise PluginDependencyError(
                    f"plugin {plugin_id!r} declares dependency {dependency_id!r} "
                    "more than once"
                )
            seen.add(dependency_id)
            dependencies.append(
                parse_plugin_dependency(dependency_id, entry_point.value)
            )
        collected[plugin_id] = tuple(dependencies)
    return collected


def _packaging_bridge_warnings(
    catalog_entries: dict[str, EntryPoint],
    dependencies_by_id: dict[str, tuple[PluginDependency, ...]],
    entry_point_index: EntryPointIndex,
) -> tuple[str, ...]:
    """Report plugin dependencies whose provider is not a distribution requirement."""
    warnings: list[str] = []
    for plugin_id, dependencies in dependencies_by_id.items():
        catalog = catalog_entries.get(plugin_id)
        if catalog is None:
            continue
        requirements = entry_point_index.distribution_requirements(catalog)
        if requirements is None:
            continue
        identity = entry_point_index.distribution_identity(catalog)
        for dependency in dependencies:
            provider = catalog_entries.get(dependency.plugin_id)
            if provider is None:
                continue
            provider_identity = entry_point_index.distribution_identity(provider)
            if not provider_identity.present or provider_identity.name is None:
                continue
            if provider_identity.normalized_name == identity.normalized_name:
                continue
            if provider_identity.normalized_name in requirements:
                continue
            warnings.append(
                f"plugin {plugin_id!r} depends on plugin {dependency.plugin_id!r} "
                f"provided by distribution {provider_identity.name!r}, which "
                f"{identity.name or 'its distribution'!r} does not declare in its "
                "distribution requirements"
            )
    return tuple(warnings)


def _validate_goal_compatibility(
    plugin: Plugin,
    contract: GoalContract,
    *,
    source: str,
) -> None:
    if not isinstance(plugin, contract.plugin_type):
        raise PluginLoadError(
            f"{source} must provide {contract.plugin_type.__module__}."
            f"{contract.plugin_type.__qualname__}"
        )
    requirement = getattr(plugin, "goal_requirement", None)
    if requirement != contract.requirement:
        raise PluginLoadError(
            f"{source} requires goal {requirement!r}, expected {contract.requirement!r}"
        )


def validate_goal_plugins(
    plugins: Iterable[Plugin],
    contract: GoalContract,
    *,
    source: str,
) -> tuple[Plugin, ...]:
    """Validate explicitly supplied plugins against one goal contract."""
    result = tuple(plugins)
    for plugin in result:
        _validate_goal_compatibility(plugin, contract, source=source)
    return result


def _policy_ids(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, str):
        raise TypeError("plugin IDs must be an iterable, not a string")
    try:
        result = frozenset(values)
    except TypeError as error:
        raise TypeError("plugin IDs must be iterable strings") from error
    for plugin_id in result:
        validate_global_identifier(plugin_id, label="plugin policy ID")
    return result


def _remove_namespace(namespace: str) -> None:
    for module_name in tuple(sys.modules):
        if module_name == namespace or module_name.startswith(f"{namespace}."):
            del sys.modules[module_name]
