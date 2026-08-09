class ContextAccessError(PermissionError):
    """Raised when a plugin accesses an undeclared context identifier."""


class MissingContextError(KeyError):
    """Raised when required context has not been written."""


class PluginPhaseError(RuntimeError):
    """Raised when a PluginAPI operation is unavailable in the current phase."""


class StateCatalogError(RuntimeError):
    """Raised when centrally stored workspace metadata is invalid."""


class UnusedContextWarning(RuntimeWarning):
    """Warns that context was written but never successfully read."""
