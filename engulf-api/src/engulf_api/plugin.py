from __future__ import annotations

import re
from abc import ABC
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .dependencies import PluginDependency
from .goals import GoalRequirement, GoalResult, Invocation
from .identifiers import validate_global_identifier
from .plugin_api import AfterGoalAPI, BeforeGoalAPI


class ElevationRequirement(StrEnum):
    """How a plugin uses operating-system elevation."""

    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginMetadata:
    """Immutable plugin-declared metadata, independent of its implementation."""

    plugin_id: str
    goal_requirement: GoalRequirement
    priority: int = 50
    elevation_requirement: ElevationRequirement = ElevationRequirement.NONE
    plugin_dependencies: tuple[PluginDependency, ...] = ()
    """Resolved from packaging metadata by the runtime, never declared in code."""
    context_reads: frozenset[str] = frozenset()
    context_writes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        plugin_id = validate_global_identifier(self.plugin_id, label="plugin_id")
        if not isinstance(self.goal_requirement, GoalRequirement):
            raise TypeError("goal_requirement must be a GoalRequirement")
        if type(self.priority) is not int:
            raise TypeError(f"priority for plugin {plugin_id!r} must be an integer")
        if not isinstance(self.elevation_requirement, ElevationRequirement):
            raise TypeError(
                f"elevation_requirement for plugin {plugin_id!r} must be an "
                "ElevationRequirement"
            )
        if type(self.plugin_dependencies) is not tuple:
            raise TypeError(
                f"plugin_dependencies for plugin {plugin_id!r} must be a tuple"
            )
        if any(
            not isinstance(dependency, PluginDependency)
            for dependency in self.plugin_dependencies
        ):
            raise TypeError(
                f"plugin_dependencies for plugin {plugin_id!r} must contain only "
                "PluginDependency values"
            )
        _validate_context_ids(
            self.context_reads,
            plugin_id=plugin_id,
            field="context_reads",
        )
        _validate_context_ids(
            self.context_writes,
            plugin_id=plugin_id,
            field="context_writes",
        )


class PluginSourceKind(StrEnum):
    """How a runtime obtained a normal plugin implementation."""

    DIRECTORY = "directory"
    INSTALLED = "installed"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginSource:
    """Immutable observed provenance; this is not a trust decision."""

    kind: PluginSourceKind
    target: str
    distribution_name: str | None = None
    distribution_version: str | None = None
    entry_point_group: str | None = None
    entry_point_value: str | None = None
    directory: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PluginSourceKind):
            raise TypeError("plugin source kind must be a PluginSourceKind")
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("plugin source target must be a nonempty string")
        for field, value in (
            ("distribution_name", self.distribution_name),
            ("distribution_version", self.distribution_version),
            ("entry_point_group", self.entry_point_group),
            ("entry_point_value", self.entry_point_value),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"plugin source {field} must be a nonempty string")
        if self.directory is not None and (
            not isinstance(self.directory, Path) or not self.directory.is_absolute()
        ):
            raise ValueError("plugin source directory must be an absolute pathlib.Path")
        if self.kind is PluginSourceKind.INSTALLED:
            if self.entry_point_group is None or self.entry_point_value is None:
                raise ValueError(
                    "installed plugin sources require an entry-point group and value"
                )
            if self.directory is not None:
                raise ValueError("installed plugin sources cannot have a directory")
        elif self.kind is PluginSourceKind.DIRECTORY:
            if self.directory is None:
                raise ValueError("directory plugin sources require a directory")
            if any(
                value is not None
                for value in (
                    self.distribution_name,
                    self.distribution_version,
                    self.entry_point_group,
                    self.entry_point_value,
                )
            ):
                raise ValueError(
                    "directory plugin sources cannot have distribution metadata"
                )

    @property
    def normalized_distribution_name(self) -> str | None:
        if self.distribution_name is None:
            return None
        return re.sub(r"[-_.]+", "-", self.distribution_name).lower()


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivePlugin:
    """Implementation-free record for one active normal plugin."""

    metadata: PluginMetadata
    source: PluginSource

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, PluginMetadata):
            raise TypeError("active plugin metadata must be PluginMetadata")
        if not isinstance(self.source, PluginSource):
            raise TypeError("active plugin source must be PluginSource")

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
    def plugin_dependencies(self) -> tuple[PluginDependency, ...]:
        return self.metadata.plugin_dependencies

    @property
    def context_reads(self) -> frozenset[str]:
        return self.metadata.context_reads

    @property
    def context_writes(self) -> frozenset[str]:
        return self.metadata.context_writes


class Plugin(ABC):
    """Base contract shared by every goal-specific plugin adapter."""

    plugin_id: str = ""
    """Globally unique, dot-qualified identifier for this plugin."""

    goal_requirement: GoalRequirement
    """Goal ID and API major implemented by this plugin adapter."""

    priority: int = 50
    """Activation priority. Higher values activate before lower values."""

    elevation_requirement: ElevationRequirement = ElevationRequirement.NONE
    """Whether this plugin can or must run with elevated privileges."""

    context_reads: frozenset[str] = frozenset()
    """Context identifiers this plugin may read."""

    context_writes: frozenset[str] = frozenset()
    """Context identifiers this plugin may create or overwrite."""

    @property
    def metadata(self) -> PluginMetadata:
        """Return one immutable snapshot of this adapter's declared metadata.

        Plugin dependencies are absent here: a runtime reads them from packaging
        metadata and merges them into the snapshot it keeps.
        """
        return PluginMetadata(
            plugin_id=self.plugin_id,
            goal_requirement=self.goal_requirement,
            priority=self.priority,
            elevation_requirement=self.elevation_requirement,
            context_reads=self.context_reads,
            context_writes=self.context_writes,
        )

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        """Optionally reject or short-circuit an invocation before its goal."""
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        """Observe or transform the result as ordered middleware."""
        return result


def plugin_name(plugin: Plugin) -> str:
    plugin_type = type(plugin)
    return f"{plugin_type.__module__}.{plugin_type.__qualname__}"


def _validate_context_ids(
    values: object,
    *,
    plugin_id: str,
    field: str,
) -> None:
    if type(values) is not frozenset:
        raise TypeError(f"{field} for plugin {plugin_id!r} must be a frozenset")
    for context_id in values:
        validate_global_identifier(
            context_id,
            label=f"context identifier in {field} for {plugin_id!r}",
        )
