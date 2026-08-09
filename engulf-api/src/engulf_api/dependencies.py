from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identifiers import validate_global_identifier


class DependencyPosition(StrEnum):
    """Position of a dependency relative to the plugin declaring it."""

    BEFORE = "before"
    AFTER = "after"


@dataclass(frozen=True, slots=True)
class PluginDependency:
    """A hard plugin dependency with independent per-phase ordering."""

    plugin_id: str
    preprocess: DependencyPosition | None = DependencyPosition.BEFORE
    postprocess: DependencyPosition | None = DependencyPosition.AFTER

    def __post_init__(self) -> None:
        validate_global_identifier(self.plugin_id, label="dependency plugin_id")
        for phase, position in (
            ("preprocess", self.preprocess),
            ("postprocess", self.postprocess),
        ):
            if position is not None and not isinstance(position, DependencyPosition):
                raise TypeError(f"{phase} must be a DependencyPosition or None")
