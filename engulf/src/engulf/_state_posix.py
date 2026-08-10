from __future__ import annotations

import errno
import fcntl
import os
import pwd
import shutil
import stat
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from engulf_api import LockTimeoutError, StateCatalogError

from ._state_platform import _HeldFileLock, _StateOwner


@dataclass(frozen=True, slots=True)
class _PosixOwnerData:
    uid: int
    gid: int
    under_sudo: bool


class _PosixHeldFileLock:
    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor < 0:
            return
        self._descriptor = -1
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


class _PosixStatePlatform:
    name = "posix"

    def is_elevated(self) -> bool:
        return os.geteuid() == 0

    def resolve_owner(self, environment: Mapping[str, str]) -> _StateOwner:
        effective_uid = os.geteuid()
        effective_gid = os.getegid()
        owner_uid = effective_uid
        owner_gid = effective_gid
        under_sudo = False

        if effective_uid == 0:
            sudo_uid = _parse_nonnegative_integer(environment.get("SUDO_UID"))
            sudo_gid = _parse_nonnegative_integer(environment.get("SUDO_GID"))
            if sudo_uid not in {None, 0} and sudo_gid is not None:
                try:
                    account = pwd.getpwuid(sudo_uid)
                except KeyError:
                    account = None
                if account is not None:
                    owner_uid = sudo_uid
                    owner_gid = sudo_gid
                    under_sudo = True

        try:
            account = pwd.getpwuid(owner_uid)
        except KeyError as error:
            raise RuntimeError(
                f"state owner UID does not exist: {owner_uid}"
            ) from error
        return _StateOwner(
            self,
            f"posix:{owner_uid}:{owner_gid}",
            Path(account.pw_dir),
            self.is_elevated(),
            _PosixOwnerData(owner_uid, owner_gid, under_sudo),
        )

    def default_state_home(
        self,
        owner: _StateOwner,
        environment: Mapping[str, str],
    ) -> Path:
        data = _owner_data(owner)
        if not data.under_sudo:
            configured = environment.get("XDG_STATE_HOME", "")
            if configured:
                path = Path(configured)
                if path.is_absolute():
                    return path.resolve(strict=False)
        return (owner.home / ".local" / "state").resolve(strict=False)

    def is_link(self, path: Path) -> bool:
        return path.is_symlink()

    def ensure_directory(self, directory: Path, owner: _StateOwner) -> None:
        missing: list[Path] = []
        current = directory
        while not os.path.lexists(current):
            missing.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        if os.path.lexists(current):
            self.require_directory(current)

        for path in reversed(missing):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                self.require_directory(path)
                continue
            path.chmod(0o700)
            _chown_path(path, owner)

        self.require_directory(directory)

    def require_directory(self, directory: Path) -> None:
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise StateCatalogError(f"state path is not a directory: {directory}")

    def read_bytes_no_follow(self, path: Path) -> bytes:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)

    def atomic_write(self, path: Path, data: bytes, owner: _StateOwner) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            _chown_descriptor(descriptor, owner)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, path)
            directory_descriptor = os.open(
                path.parent,
                os.O_RDONLY | os.O_DIRECTORY,
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)

    def remove_path(self, path: Path) -> None:
        if not os.path.lexists(path):
            return
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    def acquire_file_lock(
        self,
        path: Path,
        *,
        owner: _StateOwner,
        exclusive: bool,
        deadline: float | None,
        timeout_message: str,
    ) -> _HeldFileLock:
        self.ensure_directory(path.parent, owner)
        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StateCatalogError(
                    f"lock file cannot be a symlink: {path}"
                ) from error
            raise

        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise StateCatalogError(f"lock path is not a regular file: {path}")
            os.fchmod(descriptor, 0o600)
            _chown_descriptor(descriptor, owner)
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            if deadline is None:
                while True:
                    try:
                        fcntl.flock(descriptor, operation)
                        break
                    except InterruptedError:
                        continue
            else:
                operation |= fcntl.LOCK_NB
                while True:
                    try:
                        fcntl.flock(descriptor, operation)
                        break
                    except InterruptedError:
                        continue
                    except OSError as error:
                        if error.errno not in {errno.EACCES, errno.EAGAIN}:
                            raise
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise LockTimeoutError(timeout_message) from None
                        time.sleep(min(0.01, remaining))
        except BaseException:
            os.close(descriptor)
            raise
        return _PosixHeldFileLock(descriptor)


def _owner_data(owner: _StateOwner) -> _PosixOwnerData:
    data = owner.native
    if owner.platform is not POSIX_STATE_PLATFORM or not isinstance(
        data,
        _PosixOwnerData,
    ):
        raise TypeError("state owner does not belong to the POSIX backend")
    return data


def _parse_nonnegative_integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _chown_path(path: Path, owner: _StateOwner) -> None:
    data = _owner_data(owner)
    if os.geteuid() == 0:
        os.chown(path, data.uid, data.gid, follow_symlinks=False)


def _chown_descriptor(descriptor: int, owner: _StateOwner) -> None:
    data = _owner_data(owner)
    if os.geteuid() == 0:
        os.fchown(descriptor, data.uid, data.gid)


POSIX_STATE_PLATFORM = _PosixStatePlatform()
