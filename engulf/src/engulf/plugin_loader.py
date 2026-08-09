from __future__ import annotations

import hashlib
import heapq
import importlib.util
import itertools
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from types import ModuleType

from engulf_api import (
    PLUGIN_API_MAJOR,
    DependencyPosition,
    Plugin,
    PluginDependency,
    plugin_name,
    validate_global_identifier,
)


class PluginLoadError(RuntimeError):
    """Raised when a plugin directory or plugin module cannot be loaded."""


class PluginDependencyError(PluginLoadError):
    """Raised when plugin metadata cannot produce valid activation orders."""


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """Validated, immutable metadata for one discovered plugin."""

    plugin: Plugin
    plugin_id: str
    priority: int
    dependencies: tuple[PluginDependency, ...]
    context_reads: frozenset[str]
    context_writes: frozenset[str]
    discovery_index: int


@dataclass(frozen=True, slots=True)
class PluginOrders:
    """Independent activation orders for the two call phases."""

    preprocess: tuple[LoadedPlugin, ...]
    postprocess: tuple[LoadedPlugin, ...]


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


def plugin_entry_point_group(application_id: str) -> str:
    """Return the entry-point group used by one wrapping application."""
    normalized = normalize_application_id(application_id).replace("-", "_")
    return f"engulf.plugins.v{PLUGIN_API_MAJOR}.{normalized}"


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


def load_installed_plugins(application_id: str) -> tuple[Plugin, ...]:
    """Load installed plugins registered for an application and API major."""
    group = plugin_entry_point_group(application_id)
    try:
        discovered = entry_points(group=group)
    except Exception as error:
        raise PluginLoadError(
            f"failed to discover installed plugins in entry-point group {group!r}"
        ) from error

    plugins: list[Plugin] = []
    identifiers: set[str] = set()
    for entry_point in sorted(discovered, key=_entry_point_sort_key):
        identifier = _entry_point_identifier(entry_point)
        if identifier in identifiers:
            raise PluginLoadError(f"duplicate installed plugin: {identifier}")
        identifiers.add(identifier)
        plugins.append(_load_entry_point(entry_point, identifier))
    return tuple(plugins)


def resolve_plugin_orders(plugins: Iterable[Plugin]) -> PluginOrders:
    """Validate plugin metadata and resolve deterministic per-phase orders."""
    loaded = tuple(
        _snapshot_plugin(plugin, discovery_index)
        for discovery_index, plugin in enumerate(plugins)
    )
    by_id: dict[str, LoadedPlugin] = {}
    for item in loaded:
        existing = by_id.get(item.plugin_id)
        if existing is not None:
            raise PluginDependencyError(
                f"duplicate plugin_id {item.plugin_id!r}: "
                f"{plugin_name(existing.plugin)} and {plugin_name(item.plugin)}"
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


def _snapshot_plugin(plugin: Plugin, discovery_index: int) -> LoadedPlugin:
    name = plugin_name(plugin)
    try:
        plugin_id = plugin.plugin_id
        priority = plugin.priority
        dependencies = plugin.plugin_dependencies
        context_reads = plugin.context_reads
        context_writes = plugin.context_writes
    except Exception as error:
        raise PluginDependencyError(
            f"could not read metadata for plugin {name}"
        ) from error

    try:
        validated_plugin_id = validate_global_identifier(
            plugin_id, label=f"plugin_id for plugin {name}"
        )
    except (TypeError, ValueError) as error:
        raise PluginDependencyError(str(error)) from error
    if type(priority) is not int:
        raise PluginDependencyError(
            f"priority for plugin {validated_plugin_id!r} must be an integer"
        )
    if type(dependencies) is not tuple:
        raise PluginDependencyError(
            f"plugin_dependencies for plugin {validated_plugin_id!r} must be a tuple"
        )
    if any(not isinstance(item, PluginDependency) for item in dependencies):
        raise PluginDependencyError(
            f"plugin_dependencies for plugin {validated_plugin_id!r} must contain "
            "only PluginDependency values"
        )

    validated_reads = _validate_context_ids(
        context_reads, plugin_id=validated_plugin_id, field="context_reads"
    )
    validated_writes = _validate_context_ids(
        context_writes, plugin_id=validated_plugin_id, field="context_writes"
    )
    return LoadedPlugin(
        plugin=plugin,
        plugin_id=validated_plugin_id,
        priority=priority,
        dependencies=dependencies,
        context_reads=validated_reads,
        context_writes=validated_writes,
        discovery_index=discovery_index,
    )


def _validate_context_ids(
    values: object, *, plugin_id: str, field: str
) -> frozenset[str]:
    if type(values) is not frozenset:
        raise PluginDependencyError(
            f"{field} for plugin {plugin_id!r} must be a frozenset"
        )
    for context_id in values:
        try:
            validate_global_identifier(
                context_id, label=f"context identifier in {field} for {plugin_id!r}"
            )
        except (TypeError, ValueError) as error:
            raise PluginDependencyError(str(error)) from error
    return values


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


def _entry_point_identifier(entry_point: EntryPoint) -> str:
    distribution_name = _entry_point_distribution_name(entry_point)
    version = entry_point.dist.version if entry_point.dist is not None else "unknown"
    return f"{distribution_name} {version}:{entry_point.name}"


def _entry_point_distribution_name(entry_point: EntryPoint) -> str:
    if entry_point.dist is None:
        return "unknown-distribution"
    return entry_point.dist.name or "unknown-distribution"


def _remove_namespace(namespace: str) -> None:
    for module_name in tuple(sys.modules):
        if module_name == namespace or module_name.startswith(f"{namespace}."):
            del sys.modules[module_name]
