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
from importlib.metadata import EntryPoint, entry_points
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

    def close(self) -> None:
        """Release every materialized endpoint after abandoned discovery."""
        _close_plugin_endpoints(self.loaded_plugins)


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
) -> PluginDiscovery:
    """Select compatible directory and installed plugins for one application."""
    if not isinstance(contract, GoalContract):
        raise TypeError("contract must be a GoalContract")
    if not isinstance(policy, PluginPolicy):
        raise TypeError("policy must be a PluginPolicy")
    if not isinstance(discover_installed, bool):
        raise TypeError("discover_installed must be a boolean")
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
        catalog_entries = _entry_point_catalog(catalog_group)
        application_entry_catalogs = [
            _entry_point_catalog(
                application_plugin_entry_point_group(declaration_application_id)
            )
            for declaration_application_id in declaration_application_ids
        ]

    declared_ids: set[str] = set()
    for application_entries in application_entry_catalogs:
        for plugin_id, declaration in application_entries.items():
            catalog = catalog_entries.get(plugin_id)
            if catalog is None:
                continue
            if not _same_entry_point_source(declaration, catalog):
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

    loaded_catalog: dict[str, Plugin] = {}
    metadata: dict[int, LoadedPlugin] = {}
    if policy.include_dependencies:
        try:
            _expand_allowlist_dependencies(
                contract,
                local_by_id,
                catalog_entries,
                selected_local_ids,
                selected_catalog_ids,
                loaded_catalog,
                metadata,
                sources,
            )
        except BaseException as discovery_error:
            _cleanup_discovery_failure(discovery_error, metadata.values())
            raise

    installed_plugins: list[Plugin] = []
    selected_entries = (
        catalog_entries[plugin_id]
        for plugin_id in selected_catalog_ids
        if plugin_id in catalog_entries
    )
    try:
        for entry_point in sorted(selected_entries, key=_entry_point_sort_key):
            installed_plugin = loaded_catalog.get(entry_point.name)
            if installed_plugin is None:
                source = _installed_plugin_source(entry_point)
                installed_plugin = _load_catalog_plugin(entry_point, contract)
                sources[id(installed_plugin)] = source
            installed_plugins.append(installed_plugin)
    except BaseException as discovery_error:
        _cleanup_discovery_failure(discovery_error, metadata.values())
        raise

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
            snapshot = metadata.get(id(plugin))
            if snapshot is None:
                snapshot = _snapshot_plugin(
                    plugin,
                    discovery_index,
                    source=sources[id(plugin)],
                )
            elif snapshot.discovery_index != discovery_index:
                snapshot = replace(snapshot, discovery_index=discovery_index)
            loaded_plugins.append(snapshot)
    except BaseException as discovery_error:
        _cleanup_discovery_failure(
            discovery_error,
            (*metadata.values(), *loaded_plugins),
        )
        raise
    return PluginDiscovery(
        missing_policy_ids=missing,
        loaded_plugins=tuple(loaded_plugins),
    )


def _expand_allowlist_dependencies(
    contract: GoalContract,
    local_by_id: dict[str, list[Plugin]],
    catalog_entries: dict[str, EntryPoint],
    selected_local_ids: set[str],
    selected_catalog_ids: set[str],
    loaded_catalog: dict[str, Plugin],
    metadata: dict[int, LoadedPlugin],
    sources: dict[int, PluginSource],
) -> None:
    pending = list(selected_local_ids | selected_catalog_ids)
    heapq.heapify(pending)
    expanded: set[str] = set()

    while pending:
        plugin_id = heapq.heappop(pending)
        if plugin_id in expanded:
            continue
        expanded.add(plugin_id)

        plugins = list(local_by_id.get(plugin_id, ()))
        entry_point = catalog_entries.get(plugin_id)
        if entry_point is not None:
            selected_catalog_ids.add(plugin_id)
            installed = loaded_catalog.get(plugin_id)
            if installed is None:
                source = _installed_plugin_source(entry_point)
                installed = _load_catalog_plugin(entry_point, contract)
                loaded_catalog[plugin_id] = installed
                sources[id(installed)] = source
            plugins.append(installed)
        if plugin_id in local_by_id:
            selected_local_ids.add(plugin_id)

        for plugin in plugins:
            snapshot = metadata.get(id(plugin))
            if snapshot is None:
                snapshot = _snapshot_plugin(plugin, 0, source=sources[id(plugin)])
                metadata[id(plugin)] = snapshot
            for dependency in snapshot.dependencies:
                dependency_id = dependency.plugin_id
                if dependency_id in expanded:
                    continue
                if dependency_id in local_by_id:
                    selected_local_ids.add(dependency_id)
                if dependency_id in catalog_entries:
                    selected_catalog_ids.add(dependency_id)
                heapq.heappush(pending, dependency_id)


def _load_catalog_plugin(
    entry_point: EntryPoint,
    contract: GoalContract,
) -> Plugin:
    identifier = _entry_point_identifier(entry_point)
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
) -> LoadedPlugin:
    name = plugin_name(plugin)
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


def _entry_point_sort_key(entry_point: EntryPoint) -> tuple[str, str, str]:
    distribution_name = _entry_point_distribution_name(entry_point)
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
) -> PluginSource:
    distribution = entry_point.dist
    return PluginSource(
        kind=PluginSourceKind.INSTALLED,
        target=entry_point.value,
        distribution_name=(None if distribution is None else distribution.name or None),
        distribution_version=(
            None if distribution is None else distribution.version or None
        ),
        entry_point_group=entry_point.group,
        entry_point_value=entry_point.value,
    )


def _entry_point_identifier(entry_point: EntryPoint) -> str:
    distribution_name = _entry_point_distribution_name(entry_point)
    version = entry_point.dist.version if entry_point.dist is not None else "unknown"
    return f"{distribution_name} {version}:{entry_point.name}"


def _entry_point_distribution_name(entry_point: EntryPoint) -> str:
    if entry_point.dist is None:
        return "unknown-distribution"
    return entry_point.dist.name or "unknown-distribution"


def _entry_point_catalog(group: str) -> dict[str, EntryPoint]:
    try:
        discovered = entry_points(group=group)
    except Exception as error:
        raise PluginLoadError(
            f"failed to discover installed plugins in entry-point group {group!r}"
        ) from error

    catalog: dict[str, EntryPoint] = {}
    for entry_point in sorted(discovered, key=_entry_point_sort_key):
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
                f"{_entry_point_identifier(existing)} and "
                f"{_entry_point_identifier(entry_point)}"
            )
        catalog[plugin_id] = entry_point
    return catalog


def _same_entry_point_source(left: EntryPoint, right: EntryPoint) -> bool:
    if left.value != right.value:
        return False
    left_distribution = left.dist
    right_distribution = right.dist
    if left_distribution is None or right_distribution is None:
        return left_distribution is None and right_distribution is None
    return (
        _normalize_distribution_name(left_distribution.name or "")
        == _normalize_distribution_name(right_distribution.name or "")
        and left_distribution.version == right_distribution.version
    )


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
