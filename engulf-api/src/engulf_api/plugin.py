from __future__ import annotations

from abc import ABC
from enum import StrEnum

from .dependencies import PluginDependency
from .goals import GoalRequirement, GoalResult, Invocation
from .plugin_api import AfterGoalAPI, BeforeGoalAPI


class ElevationRequirement(StrEnum):
    """How a plugin uses operating-system elevation."""

    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


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
