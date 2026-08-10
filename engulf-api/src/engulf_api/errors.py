class ContextAccessError(PermissionError):
    """Raised when a plugin accesses an undeclared context identifier."""


class MissingContextError(KeyError):
    """Raised when required context has not been written."""


class PluginPhaseError(RuntimeError):
    """Raised when an API operation is unavailable in the current lifecycle phase."""


class LockTimeoutError(TimeoutError):
    """A state transaction or resource lease could not be acquired in time."""


class StateCatalogError(RuntimeError):
    """Raised when centrally stored workspace metadata is invalid."""


class UnusedContextWarning(RuntimeWarning):
    """Warns that context was written but never successfully read."""
