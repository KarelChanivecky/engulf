from __future__ import annotations

from abc import ABC

from engulf_api import (
    DiagnosticsAPI,
    GoalRequirement,
    InvocationAPI,
    Plugin,
    RegistrationAPI,
)

from .models import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    PreparedCallEvent,
)
from .registry import ArgumentRegistry, CompletionRegistry

EXECUTABLE_WRAPPER_GOAL_ID = "org.engulf.executable-wrapper"
EXECUTABLE_WRAPPER_API_MAJOR = 1
EXECUTABLE_WRAPPER_API_VERSION = "1.0.0"


class HelpAPI(DiagnosticsAPI):
    """Logger available while executable-wrapper help is collected."""


class ExecutableWrapperPlugin(Plugin, ABC):
    """Plugin adapter for the executable-wrapper goal contract."""

    goal_requirement = GoalRequirement(
        EXECUTABLE_WRAPPER_GOAL_ID,
        EXECUTABLE_WRAPPER_API_MAJOR,
    )

    def register_arguments(
        self,
        registry: ArgumentRegistry,
        api: RegistrationAPI,
    ) -> None:
        """Register wrapper options used only for completion metadata."""

    def register_completions(
        self,
        registry: CompletionRegistry,
        api: RegistrationAPI,
    ) -> None:
        """Register wrapper completion candidates and providers."""

    def help(self, api: HelpAPI) -> str:
        """Return this plugin's executable-wrapper help block."""
        return ""

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        """Inspect the original call and return a side-effect-free contribution."""
        return None

    def prepare_call(
        self,
        event: PreparedCallEvent,
        api: InvocationAPI,
    ) -> None:
        """Prepare external resources after edits and vetoes are resolved."""

    def after_call(
        self,
        event: AfterCallEvent,
        api: InvocationAPI,
    ) -> None:
        """Finalize a completed, rejected, or failed executable call."""
