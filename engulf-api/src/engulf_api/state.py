from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path


class StateScope(StrEnum):
    """Lifetime and visibility of one plugin state store."""

    WORKSPACE = "workspace"
    USER = "user"


class StateStore(ABC):
    """Managed files in one plugin-specific state directory."""

    @property
    @abstractmethod
    def directory(self) -> Path:
        """Create and return the plugin's state directory."""

    @abstractmethod
    def path(self, filename: str) -> Path:
        """Create the state directory and return a validated child path."""

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """Return whether a state file exists without creating its directory."""

    @abstractmethod
    def read_bytes(self, filename: str) -> bytes:
        """Read a state file as bytes."""

    @abstractmethod
    def read_text(
        self,
        filename: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        """Read a state file as text."""

    @abstractmethod
    def write_bytes(self, filename: str, data: bytes) -> None:
        """Atomically replace a state file with bytes."""

    @abstractmethod
    def write_text(
        self,
        filename: str,
        data: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> None:
        """Atomically replace a state file with encoded text."""

    @abstractmethod
    def delete(self, filename: str, *, missing_ok: bool = False) -> None:
        """Delete a state file."""


class WorkspaceState(StateStore):
    """Plugin state associated with one canonical workspace root."""

    @property
    @abstractmethod
    def root(self) -> Path:
        """Return the canonical workspace root represented by this state."""

    @abstractmethod
    def destroy(self) -> None:
        """Queue removal of this plugin's state after postprocessing."""
