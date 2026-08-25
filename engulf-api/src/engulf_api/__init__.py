from .application import ApplicationMetadata
from .dependencies import DependencyPosition, PluginDependency
from .diagnostic_extensions import (
    DiagnosticAPI,
    DiagnosticContribution,
    DiagnosticExtension,
    DiagnosticPlugin,
    DiagnosticRequest,
    PluginExecutionRecord,
)
from .diagnostics import PluginLogger
from .errors import (
    ContextAccessError,
    LockTimeoutError,
    MissingContextError,
    PluginPhaseError,
    StateCatalogError,
    UnusedContextWarning,
)
from .goals import (
    AttributedContribution,
    Goal,
    GoalContract,
    GoalPhase,
    GoalRequirement,
    GoalResult,
    GoalResultStatus,
    Invocation,
    PluginOrder,
)
from .identifiers import validate_global_identifier
from .plugin import (
    ActivePlugin,
    ElevationRequirement,
    Plugin,
    PluginMetadata,
    PluginSource,
    PluginSourceKind,
    plugin_name,
)
from .plugin_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    DiagnosticsAPI,
    GoalAPI,
    GoalSetupAPI,
    InvocationAPI,
    RegistrationAPI,
)
from .state import StateScope, StateStore, WorkspaceState
from .validation import validate_exit_code

PLUGIN_API_MAJOR = 1
PLUGIN_API_VERSION = "1.1.0"

__all__ = [
    "PLUGIN_API_MAJOR",
    "PLUGIN_API_VERSION",
    "ActivePlugin",
    "AfterGoalAPI",
    "ApplicationMetadata",
    "AttributedContribution",
    "BeforeGoalAPI",
    "ContextAccessError",
    "DependencyPosition",
    "DiagnosticAPI",
    "DiagnosticContribution",
    "DiagnosticExtension",
    "DiagnosticPlugin",
    "DiagnosticRequest",
    "DiagnosticsAPI",
    "ElevationRequirement",
    "Goal",
    "GoalAPI",
    "GoalContract",
    "GoalPhase",
    "GoalRequirement",
    "GoalResult",
    "GoalResultStatus",
    "GoalSetupAPI",
    "Invocation",
    "InvocationAPI",
    "LockTimeoutError",
    "MissingContextError",
    "Plugin",
    "PluginDependency",
    "PluginExecutionRecord",
    "PluginLogger",
    "PluginMetadata",
    "PluginOrder",
    "PluginPhaseError",
    "PluginSource",
    "PluginSourceKind",
    "RegistrationAPI",
    "StateCatalogError",
    "StateScope",
    "StateStore",
    "UnusedContextWarning",
    "WorkspaceState",
    "plugin_name",
    "validate_exit_code",
    "validate_global_identifier",
]
