from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from engulf_api import (
    ElevationRequirement,
    GoalRequirement,
    PluginDependency,
    PluginMetadata,
)


class PluginSourceKind(StrEnum):
    """How the runtime obtained one plugin implementation."""

    DIRECTORY = "directory"
    INSTALLED = "installed"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginSource:
    """Runtime-captured source metadata kept separate from plugin declarations."""

    kind: PluginSourceKind
    target: str
    distribution_name: str | None = None
    distribution_version: str | None = None
    entry_point_group: str | None = None
    entry_point_value: str | None = None
    directory: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PluginSourceKind):
            raise TypeError("plugin source kind must be a PluginSourceKind")
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("plugin source target must be a nonempty string")
        for field, value in (
            ("distribution_name", self.distribution_name),
            ("distribution_version", self.distribution_version),
            ("entry_point_group", self.entry_point_group),
            ("entry_point_value", self.entry_point_value),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"plugin source {field} must be a nonempty string")
        if self.directory is not None and (
            not isinstance(self.directory, Path) or not self.directory.is_absolute()
        ):
            raise ValueError("plugin source directory must be an absolute pathlib.Path")
        if self.kind is PluginSourceKind.INSTALLED:
            if self.entry_point_group is None or self.entry_point_value is None:
                raise ValueError(
                    "installed plugin sources require an entry-point group and value"
                )
            if self.directory is not None:
                raise ValueError("installed plugin sources cannot have a directory")
        elif self.kind is PluginSourceKind.DIRECTORY:
            if self.directory is None:
                raise ValueError("directory plugin sources require a directory")
            if any(
                value is not None
                for value in (
                    self.distribution_name,
                    self.distribution_version,
                    self.entry_point_group,
                    self.entry_point_value,
                )
            ):
                raise ValueError(
                    "directory plugin sources cannot have distribution metadata"
                )

    @property
    def normalized_distribution_name(self) -> str | None:
        if self.distribution_name is None:
            return None
        return _normalize_distribution_name(self.distribution_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivePlugin:
    """Public implementation-free description of one active plugin."""

    metadata: PluginMetadata
    source: PluginSource

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, PluginMetadata):
            raise TypeError("active plugin metadata must be PluginMetadata")
        if not isinstance(self.source, PluginSource):
            raise TypeError("active plugin source must be PluginSource")

    @property
    def plugin_id(self) -> str:
        return self.metadata.plugin_id

    @property
    def goal_requirement(self) -> GoalRequirement:
        return self.metadata.goal_requirement

    @property
    def priority(self) -> int:
        return self.metadata.priority

    @property
    def elevation_requirement(self) -> ElevationRequirement:
        return self.metadata.elevation_requirement

    @property
    def dependencies(self) -> tuple[PluginDependency, ...]:
        return self.metadata.plugin_dependencies

    @property
    def plugin_dependencies(self) -> tuple[PluginDependency, ...]:
        return self.metadata.plugin_dependencies

    @property
    def context_reads(self) -> frozenset[str]:
        return self.metadata.context_reads

    @property
    def context_writes(self) -> frozenset[str]:
        return self.metadata.context_writes


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()
