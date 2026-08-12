from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from engulf_api import ApplicationMetadata, Goal

from .application import Application
from .diagnostic_extensions import DiagnosticIsolationConfig
from .diagnostics import LoggingConfig, validate_display_name
from .plugin_loader import (
    PluginPolicy,
    normalize_application_id,
    normalize_plugin_declaration_application_ids,
)
from .state import StateHomeResolver, WorkspaceRootResolver

type GoalFactory[ResultT] = Callable[[], Goal[ResultT]]


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationDefinition[ResultT]:
    """Reusable, side-effect-free configuration for one application identity."""

    application_id: str
    display_name: str
    goal_factory: GoalFactory[ResultT]
    vendor: str
    product: str
    short_product_name: str
    version: str
    plugin_policy: PluginPolicy = field(default_factory=PluginPolicy.declared)
    required_plugin_ids: frozenset[str] = frozenset()
    logging_config: LoggingConfig = field(default_factory=LoggingConfig)
    workspace_root_resolver: WorkspaceRootResolver | None = None
    state_home_resolver: StateHomeResolver | None = None
    plugin_declaration_application_ids: tuple[str, ...] = ()
    diagnostic_isolation_config: DiagnosticIsolationConfig = field(
        default_factory=DiagnosticIsolationConfig
    )

    def __post_init__(self) -> None:
        if not callable(self.goal_factory):
            raise TypeError("goal_factory must be callable")
        if not isinstance(self.plugin_policy, PluginPolicy):
            raise TypeError("plugin_policy must be a PluginPolicy")
        if type(self.required_plugin_ids) is not frozenset:
            raise TypeError("required_plugin_ids must be a frozenset")
        if not isinstance(self.logging_config, LoggingConfig):
            raise TypeError("logging_config must be a LoggingConfig")
        if not isinstance(self.diagnostic_isolation_config, DiagnosticIsolationConfig):
            raise TypeError(
                "diagnostic_isolation_config must be a DiagnosticIsolationConfig"
            )
        if self.workspace_root_resolver is not None and not callable(
            self.workspace_root_resolver
        ):
            raise TypeError("workspace_root_resolver must be callable")
        if self.state_home_resolver is not None and not callable(
            self.state_home_resolver
        ):
            raise TypeError("state_home_resolver must be callable")

        required_ids = PluginPolicy.declared(
            include=self.required_plugin_ids
        ).plugin_ids
        application_id = normalize_application_id(self.application_id)
        display_name = validate_display_name(self.display_name)
        ApplicationMetadata(
            application_id=application_id,
            display_name=display_name,
            vendor=self.vendor,
            product=self.product,
            short_product_name=self.short_product_name,
            version=self.version,
        )
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "required_plugin_ids", required_ids)
        object.__setattr__(
            self,
            "plugin_policy",
            self.plugin_policy.including(required_ids),
        )
        object.__setattr__(
            self,
            "plugin_declaration_application_ids",
            normalize_plugin_declaration_application_ids(
                application_id,
                self.plugin_declaration_application_ids,
            ),
        )

    @property
    def application_metadata(self) -> ApplicationMetadata:
        return ApplicationMetadata(
            application_id=self.application_id,
            display_name=self.display_name,
            vendor=self.vendor,
            product=self.product,
            short_product_name=self.short_product_name,
            version=self.version,
        )

    def edition(
        self,
        *,
        display_name: str,
        vendor: str | None = None,
        product: str | None = None,
        short_product_name: str | None = None,
        version: str | None = None,
        include_plugins: Iterable[str] = (),
        require_plugins: Iterable[str] = (),
    ) -> ApplicationDefinition[ResultT]:
        """Return an additive edition sharing this logical application identity."""
        required_ids = PluginPolicy.declared(include=require_plugins).plugin_ids
        policy = self.plugin_policy.including(include_plugins).including(required_ids)
        return replace(
            self,
            display_name=display_name,
            vendor=self.vendor if vendor is None else vendor,
            product=self.product if product is None else product,
            short_product_name=(
                self.short_product_name
                if short_product_name is None
                else short_product_name
            ),
            version=self.version if version is None else version,
            plugin_policy=policy,
            required_plugin_ids=self.required_plugin_ids | required_ids,
        )

    def fork(
        self,
        *,
        application_id: str,
        display_name: str,
        vendor: str | None = None,
        product: str | None = None,
        short_product_name: str | None = None,
        version: str | None = None,
        include_plugins: Iterable[str] = (),
        require_plugins: Iterable[str] = (),
        inherit_declarations: bool = False,
    ) -> ApplicationDefinition[ResultT]:
        """Return an additive definition with an independent application identity."""
        if type(inherit_declarations) is not bool:
            raise TypeError("inherit_declarations must be a boolean")
        required_ids = PluginPolicy.declared(include=require_plugins).plugin_ids
        policy = self.plugin_policy.including(include_plugins).including(required_ids)
        declarations = (
            self.plugin_declaration_application_ids if inherit_declarations else ()
        )
        return replace(
            self,
            application_id=application_id,
            display_name=display_name,
            vendor=self.vendor if vendor is None else vendor,
            product=self.product if product is None else product,
            short_product_name=(
                self.short_product_name
                if short_product_name is None
                else short_product_name
            ),
            version=self.version if version is None else version,
            plugin_policy=policy,
            required_plugin_ids=self.required_plugin_ids | required_ids,
            plugin_declaration_application_ids=declarations,
        )

    def create(
        self,
        *,
        plugin_dir: str | os.PathLike[str] | None = None,
        discover_installed: bool = True,
    ) -> Application[ResultT]:
        """Create a fresh managed application from this definition."""
        return Application(
            self.application_id,
            self.goal_factory(),
            display_name=self.display_name,
            vendor=self.vendor,
            product=self.product,
            short_product_name=self.short_product_name,
            version=self.version,
            plugin_policy=self.plugin_policy,
            required_plugin_ids=self.required_plugin_ids,
            plugin_declaration_application_ids=(
                self.plugin_declaration_application_ids
            ),
            logging_config=self.logging_config,
            plugin_dir=plugin_dir,
            discover_installed=discover_installed,
            workspace_root_resolver=self.workspace_root_resolver,
            state_home_resolver=self.state_home_resolver,
            diagnostic_isolation_config=self.diagnostic_isolation_config,
        )


__all__ = ["ApplicationDefinition", "GoalFactory"]
