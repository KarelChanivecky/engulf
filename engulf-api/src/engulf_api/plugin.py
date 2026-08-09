from __future__ import annotations

from abc import ABC, abstractmethod

from .dependencies import PluginDependency
from .models import AfterCallEvent, BeforeCallEvent
from .plugin_api import PluginAPI
from .registry import ArgumentRegistry, CompletionRegistry


class Plugin(ABC):
    plugin_id: str = ""
    """Globally unique, dot-qualified identifier for this plugin."""

    priority: int = 50
    """Activation priority. Higher values activate before lower values."""

    plugin_dependencies: tuple[PluginDependency, ...] = ()
    """Hard dependencies and their phase-specific ordering constraints."""

    context_reads: frozenset[str] = frozenset()
    """Context identifiers this plugin may read."""

    context_writes: frozenset[str] = frozenset()
    """Context identifiers this plugin may create or overwrite."""

    @abstractmethod
    def help(self) -> str:
        """Return the plugin-specific help block."""

    def register_arguments(self, registry: ArgumentRegistry) -> None:
        """Register wrapper argument metadata used by completion."""

    def register_completions(self, registry: CompletionRegistry) -> None:
        """Register static or dynamic completion candidates."""

    def before_call(self, event: BeforeCallEvent, api: PluginAPI) -> None:
        """Inspect a call and use preprocessing capabilities."""

    def after_call(self, event: AfterCallEvent, api: PluginAPI) -> None:
        """Observe a completed, preempted, or failed call."""


def plugin_name(plugin: Plugin) -> str:
    plugin_type = type(plugin)
    return f"{plugin_type.__module__}.{plugin_type.__qualname__}"
