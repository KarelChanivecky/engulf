from .dependencies import DependencyPosition, PluginDependency
from .errors import (
    ContextAccessError,
    MissingContextError,
    PluginPhaseError,
    UnusedContextWarning,
)
from .identifiers import validate_global_identifier
from .models import (
    AdditionPlacement,
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
)
from .plugin import Plugin, plugin_name
from .plugin_api import PluginAPI
from .registry import (
    ArgumentRegistry,
    CandidateLike,
    CompletionCallable,
    CompletionCandidate,
    CompletionContext,
    CompletionPredicate,
    CompletionProvider,
    CompletionRegistry,
    OptionSpec,
    Shell,
    invoke_provider,
    normalize_candidate,
)

PLUGIN_API_MAJOR = 1
PLUGIN_API_VERSION = "1.2.0"

__all__ = [
    "PLUGIN_API_MAJOR",
    "PLUGIN_API_VERSION",
    "AdditionPlacement",
    "AfterCallEvent",
    "ArgumentRegistry",
    "BeforeCallEvent",
    "CallMode",
    "CallOutcome",
    "CandidateLike",
    "CompletionCallable",
    "CompletionCandidate",
    "CompletionContext",
    "CompletionPredicate",
    "CompletionProvider",
    "CompletionRegistry",
    "ContextAccessError",
    "DependencyPosition",
    "MissingContextError",
    "OptionSpec",
    "OutcomeKind",
    "Plugin",
    "PluginAPI",
    "PluginDependency",
    "PluginPhaseError",
    "Shell",
    "UnusedContextWarning",
    "invoke_provider",
    "normalize_candidate",
    "plugin_name",
    "validate_global_identifier",
]
