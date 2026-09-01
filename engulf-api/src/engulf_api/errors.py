class ContextAccessError(PermissionError):
    """Raised when a plugin accesses an undeclared context identifier."""


class MissingContextError(KeyError):
    """Raised when required context has not been written."""


class PluginPhaseError(RuntimeError):
    """Raised when an API operation is unavailable in the current lifecycle phase."""


class PluginCallbackError(RuntimeError):
    """Raised when one plugin callback fails during a lifecycle hook or goal phase."""

    def __init__(self, plugin_id: str, phase: str, error: Exception) -> None:
        super().__init__(f"plugin {plugin_id} failed in {phase}: {error}")
        self.plugin_id = plugin_id
        self.phase = phase
        self.error = error


class LockTimeoutError(TimeoutError):
    """A state transaction or resource lease could not be acquired in time."""


class StateCatalogError(RuntimeError):
    """Raised when centrally stored workspace metadata is invalid."""


class UnusedContextWarning(RuntimeWarning):
    """Warns that context was written but never successfully read."""
