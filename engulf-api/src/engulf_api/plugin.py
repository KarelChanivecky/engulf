from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import StrEnum

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

    plugin_dependencies: tuple[PluginDependency, ...] = ()
    """Hard dependencies and their independent two-order constraints."""

    context_reads: frozenset[str] = frozenset()
    """Context identifiers this plugin may read."""

    context_writes: frozenset[str] = frozenset()
    """Context identifiers this plugin may create or overwrite."""

    @property
    def metadata(self) -> PluginMetadata:
        """Return one immutable snapshot of this adapter's declared metadata."""
        return PluginMetadata(
            plugin_id=self.plugin_id,
            goal_requirement=self.goal_requirement,
            priority=self.priority,
            elevation_requirement=self.elevation_requirement,
            plugin_dependencies=self.plugin_dependencies,
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
