from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalPhase,
    GoalResult,
    Invocation,
    Plugin,
    plugin_name,
)


class _PluginEndpoint(ABC):
    """Execution boundary used by lifecycle and goal-phase dispatch."""

    @property
    @abstractmethod
    def implementation_name(self) -> str:
        """Return a diagnostic implementation identifier."""

    @abstractmethod
    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        """Invoke the universal preprocessing hook."""

    @abstractmethod
    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        """Invoke the universal postprocessing hook."""

    @abstractmethod
    def dispatch_phase(
        self,
        phase: GoalPhase[Any, Any, Any, Any],
        event: Any,
        api: Any,
    ) -> Any:
        """Invoke one goal phase using its stable phase identity."""

    @abstractmethod
    def close(self) -> None:
        """Release resources owned by this endpoint."""


class _InProcessPluginEndpoint(_PluginEndpoint):
    """Current execution endpoint for one imported plugin instance."""

    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    @property
    def implementation_name(self) -> str:
        return plugin_name(self._plugin)

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        return self._plugin.before_goal(invocation, api)

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        return self._plugin.after_goal(invocation, result, api)

    def dispatch_phase(
        self,
        phase: GoalPhase[Any, Any, Any, Any],
        event: Any,
        api: Any,
    ) -> Any:
        return phase.local_callback(self._plugin, event, api)

    def close(self) -> None:
        return None
