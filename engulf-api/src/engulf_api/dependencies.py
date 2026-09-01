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
    """A hard plugin dependency with independent per-phase ordering.

    Runtimes derive these values from a plugin's packaging metadata; plugins do
    not declare them in code. Both orders must be stated, and at least one must
    order the dependency, because a dependency with no edge in either order is
    an ordering declaration that does nothing.
    """

    plugin_id: str
    preprocess: DependencyPosition | None
    postprocess: DependencyPosition | None

    def __post_init__(self) -> None:
        plugin_id = validate_global_identifier(
            self.plugin_id,
            label="dependency plugin_id",
        )
        for phase, position in (
            ("preprocess", self.preprocess),
            ("postprocess", self.postprocess),
        ):
            if position is not None and not isinstance(position, DependencyPosition):
                raise TypeError(f"{phase} must be a DependencyPosition or None")
        if self.preprocess is None and self.postprocess is None:
            raise ValueError(
                f"dependency on {plugin_id!r} must order it in the preprocess or "
                "the postprocess order"
            )
