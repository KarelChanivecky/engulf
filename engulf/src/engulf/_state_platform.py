from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Protocol


class _HeldFileLock(Protocol):
    def release(self) -> None:
        """Release the OS lock and close its underlying handle."""


class _StatePlatform(Protocol):
    name: str

    def is_elevated(self) -> bool:
        """Return whether the current process has platform elevation."""

    def resolve_owner(self, environment: Mapping[str, str]) -> _StateOwner:
        """Resolve the user whose state this process should manage."""

    def default_state_home(
        self,
        owner: _StateOwner,
        environment: Mapping[str, str],
    ) -> Path:
        """Return this platform's default application-state root."""

    def is_link(self, path: Path) -> bool:
        """Return whether a path is a symbolic link or equivalent redirect."""

    def ensure_directory(self, directory: Path, owner: _StateOwner) -> None:
        """Create and secure a directory without following redirected paths."""

    def require_directory(self, directory: Path) -> None:
        """Require an existing ordinary directory without following redirects."""

    def read_bytes_no_follow(self, path: Path) -> bytes:
        """Read one ordinary file without following a redirected path."""

    def atomic_write(self, path: Path, data: bytes, owner: _StateOwner) -> None:
        """Atomically replace one owner-private state file."""

    def remove_path(self, path: Path) -> None:
        """Remove one tree or redirected path without traversing a redirect."""

    def acquire_file_lock(
        self,
        path: Path,
        *,
        owner: _StateOwner,
        exclusive: bool,
        deadline: float | None,
        timeout_message: str,
    ) -> _HeldFileLock:
        """Acquire one persistent-file advisory lock."""


@dataclass(frozen=True, slots=True)
class _StateOwner:
    platform: _StatePlatform = field(repr=False, compare=False)
    identifier: str
    home: Path
    elevated: bool
    native: object = field(repr=False, compare=False)


@cache
def get_state_platform() -> _StatePlatform:
    """Return the state implementation for the running interpreter."""
    if os.name == "posix":
        from ._state_posix import POSIX_STATE_PLATFORM

        return POSIX_STATE_PLATFORM
    if os.name == "nt":
        from ._state_windows import WINDOWS_STATE_PLATFORM

        return WINDOWS_STATE_PLATFORM
    raise RuntimeError(f"Engulf state is unsupported on platform {os.name!r}")


def is_process_elevated() -> bool:
    """Return the current platform's process-elevation state."""
    return get_state_platform().is_elevated()
