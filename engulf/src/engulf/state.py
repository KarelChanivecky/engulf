from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from engulf_api import (
    CallMode,
    StateCatalogError,
    StateStore,
    WorkspaceState,
)


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Inputs available when an application resolves a workspace root."""

    application_id: str
    binary: str
    wrapper_args: tuple[str, ...]
    mode: CallMode
    cwd: Path


type WorkspaceRootResolver = Callable[[WorkspaceContext], str | os.PathLike[str]]


@dataclass(frozen=True, slots=True)
class StateHomeContext:
    """Identity available when an application selects its central state home."""

    application_id: str
    effective_uid: int
    effective_gid: int
    owner_uid: int
    owner_gid: int
    owner_home: Path
    under_sudo: bool


type StateHomeResolver = Callable[[StateHomeContext], str | os.PathLike[str]]


@dataclass(frozen=True, slots=True)
class _StateOwner:
    uid: int
    gid: int
    home: Path
    under_sudo: bool


@dataclass(frozen=True, slots=True)
class WorkspaceCleanupFailure:
    root: Path
    plugin_id: str
    error: Exception


class CallStateManager:
    """Shared state resolution and deferred cleanup for one wrapped call."""

    def __init__(
        self,
        *,
        application_id: str,
        binary: str,
        wrapper_args: tuple[str, ...],
        mode: CallMode,
        cwd: Path,
        workspace_root_resolver: WorkspaceRootResolver | None,
        state_home_resolver: StateHomeResolver | None,
        environment: Mapping[str, str],
        effective_uid: int,
        effective_gid: int,
    ) -> None:
        self._application_id = application_id
        self._workspace_context = WorkspaceContext(
            application_id,
            binary,
            wrapper_args,
            mode,
            cwd,
        )
        self._workspace_root_resolver = workspace_root_resolver
        self._state_home_resolver = state_home_resolver
        self._environment = environment
        self._effective_uid = effective_uid
        self._effective_gid = effective_gid
        self._owner: _StateOwner | None = None
        self._catalog: _StateCatalog | None = None
        self._workspace_root: Path | None = None
        self._workspace_resolved = False
        self._pending_destructions: set[tuple[Path, str]] = set()

    def user_backend(self, plugin_id: str) -> _UserStoreBackend:
        return _UserStoreBackend(self, plugin_id)

    def current_workspace_backend(self, plugin_id: str) -> _WorkspaceStoreBackend:
        return _WorkspaceStoreBackend(self, self._resolve_workspace_root(), plugin_id)

    def known_workspace_backends(
        self, plugin_id: str
    ) -> tuple[_WorkspaceStoreBackend, ...]:
        return tuple(
            _WorkspaceStoreBackend(self, root, plugin_id)
            for root in self._get_catalog().known_roots(plugin_id)
        )

    def queue_destruction(self, root: Path, plugin_id: str) -> None:
        self._pending_destructions.add((root, plugin_id))

    def finalize_destructions(self) -> tuple[WorkspaceCleanupFailure, ...]:
        failures: list[WorkspaceCleanupFailure] = []
        for root, plugin_id in sorted(
            self._pending_destructions,
            key=lambda value: (os.fspath(value[0]), value[1]),
        ):
            try:
                self._get_catalog().destroy_plugin_workspace(root, plugin_id)
            except Exception as error:  # noqa: BLE001 - every cleanup must be attempted.
                failures.append(WorkspaceCleanupFailure(root, plugin_id, error))
        return tuple(failures)

    @property
    def owner(self) -> _StateOwner:
        if self._owner is None:
            self._owner = _resolve_state_owner(
                self._effective_uid,
                self._effective_gid,
                self._environment,
            )
        return self._owner

    def user_directory(self, plugin_id: str, *, create: bool) -> Path | None:
        return self._get_catalog().user_directory(plugin_id, create=create)

    def workspace_access(
        self,
        root: Path,
        plugin_id: str,
        *,
        create: bool,
        exclusive: bool,
    ) -> AbstractContextManager[Path | None]:
        return self._get_catalog().workspace_access(
            root,
            plugin_id,
            create=create,
            exclusive=exclusive,
        )

    def _resolve_workspace_root(self) -> Path:
        if self._workspace_resolved:
            assert self._workspace_root is not None
            return self._workspace_root

        candidate: str | os.PathLike[str]
        if self._workspace_root_resolver is None:
            candidate = self._workspace_context.cwd
        else:
            candidate = self._workspace_root_resolver(self._workspace_context)

        try:
            raw_path = os.fspath(candidate)
        except TypeError as error:
            raise TypeError(
                "workspace_root_resolver must return a text path-like value"
            ) from error
        if isinstance(raw_path, bytes) or not raw_path:
            raise TypeError("workspace_root_resolver must return a non-empty text path")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._workspace_context.cwd / path
        try:
            path = path.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"workspace root cannot be resolved: {path}") from error
        if not path.is_dir():
            raise ValueError(f"workspace root is not a directory: {path}")

        self._workspace_root = path
        self._workspace_resolved = True
        return path

    def _get_catalog(self) -> _StateCatalog:
        if self._catalog is None:
            self._catalog = _StateCatalog(
                self._resolve_state_home(),
                self._application_id,
                self.owner,
            )
        return self._catalog

    def _resolve_state_home(self) -> Path:
        owner = self.owner
        context = StateHomeContext(
            application_id=self._application_id,
            effective_uid=self._effective_uid,
            effective_gid=self._effective_gid,
            owner_uid=owner.uid,
            owner_gid=owner.gid,
            owner_home=owner.home,
            under_sudo=owner.under_sudo,
        )
        if self._state_home_resolver is not None:
            candidate = self._state_home_resolver(context)
            try:
                raw_path = os.fspath(candidate)
            except TypeError as error:
                raise TypeError(
                    "state_home_resolver must return a text path-like value"
                ) from error
            if isinstance(raw_path, bytes) or not raw_path:
                raise TypeError("state_home_resolver must return a non-empty text path")
            path = Path(raw_path)
            if not path.is_absolute():
                raise ValueError("state_home_resolver must return an absolute path")
            return path.resolve(strict=False)

        if not owner.under_sudo:
            configured = self._environment.get("XDG_STATE_HOME", "")
            if configured:
                path = Path(configured)
                if path.is_absolute():
                    return path.resolve(strict=False)
        return (owner.home / ".local" / "state").resolve(strict=False)


class RuntimeStateStore(StateStore):
    def __init__(
        self,
        backend: _UserStoreBackend | _WorkspaceStoreBackend,
        require_active: Callable[[str], None],
    ) -> None:
        self._backend = backend
        self._require_active = require_active

    @property
    def directory(self) -> Path:
        self._require_active("state.directory")
        with self._backend.access(create=True, exclusive=True) as directory:
            assert directory is not None
            return directory

    def path(self, filename: str) -> Path:
        self._require_active("state.path")
        name = _validate_filename(filename)
        with self._backend.access(create=True, exclusive=True) as directory:
            assert directory is not None
            return directory / name

    def exists(self, filename: str) -> bool:
        self._require_active("state.exists")
        name = _validate_filename(filename)
        with self._backend.access(create=False, exclusive=False) as directory:
            if directory is None:
                return False
            path = directory / name
            if path.is_symlink():
                raise StateCatalogError(f"state file cannot be a symlink: {path}")
            return path.exists()

    def read_bytes(self, filename: str) -> bytes:
        self._require_active("state.read_bytes")
        name = _validate_filename(filename)
        with self._backend.access(create=False, exclusive=False) as directory:
            if directory is None:
                raise FileNotFoundError(filename)
            return _read_bytes_no_follow(directory / name)

    def read_text(
        self,
        filename: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        return self.read_bytes(filename).decode(encoding, errors)

    def write_bytes(self, filename: str, data: bytes) -> None:
        self._require_active("state.write_bytes")
        name = _validate_filename(filename)
        if not isinstance(data, bytes):
            raise TypeError("state data must be bytes")
        with self._backend.access(create=True, exclusive=True) as directory:
            assert directory is not None
            _atomic_write(directory / name, data, self._backend.owner)

    def write_text(
        self,
        filename: str,
        data: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> None:
        self._require_active("state.write_text")
        if not isinstance(data, str):
            raise TypeError("state data must be a string")
        self.write_bytes(filename, data.encode(encoding, errors))

    def delete(self, filename: str, *, missing_ok: bool = False) -> None:
        self._require_active("state.delete")
        name = _validate_filename(filename)
        if not isinstance(missing_ok, bool):
            raise TypeError("missing_ok must be a boolean")
        with self._backend.access(create=False, exclusive=True) as directory:
            if directory is None:
                if missing_ok:
                    return
                raise FileNotFoundError(filename)
            (directory / name).unlink(missing_ok=missing_ok)


class RuntimeWorkspaceState(RuntimeStateStore, WorkspaceState):
    def __init__(
        self,
        backend: _WorkspaceStoreBackend,
        require_active: Callable[[str], None],
    ) -> None:
        super().__init__(backend, require_active)
        self._workspace_backend = backend

    @property
    def root(self) -> Path:
        self._require_active("workspace.root")
        return self._workspace_backend.root

    def destroy(self) -> None:
        self._require_active("workspace.destroy")
        self._workspace_backend.manager.queue_destruction(
            self._workspace_backend.root,
            self._workspace_backend.plugin_id,
        )


class _UserStoreBackend:
    def __init__(self, manager: CallStateManager, plugin_id: str) -> None:
        self.manager = manager
        self.plugin_id = plugin_id

    @property
    def owner(self) -> _StateOwner:
        return self.manager.owner

    def access(
        self, *, create: bool, exclusive: bool
    ) -> AbstractContextManager[Path | None]:
        del exclusive

        @contextmanager
        def access_directory() -> Iterator[Path | None]:
            yield self.manager.user_directory(self.plugin_id, create=create)

        return access_directory()


class _WorkspaceStoreBackend:
    def __init__(self, manager: CallStateManager, root: Path, plugin_id: str) -> None:
        self.manager = manager
        self.root = root
        self.plugin_id = plugin_id

    @property
    def owner(self) -> _StateOwner:
        return self.manager.owner

    def access(
        self, *, create: bool, exclusive: bool
    ) -> AbstractContextManager[Path | None]:
        return self.manager.workspace_access(
            self.root,
            self.plugin_id,
            create=create,
            exclusive=exclusive,
        )


class _StateCatalog:
    _SCHEMA_VERSION = 1

    def __init__(
        self, state_home: Path, application_id: str, owner: _StateOwner
    ) -> None:
        self._state_home = state_home
        self._application_id = application_id
        self._owner = owner
        self._application_directory = state_home / application_id
        self._user_directory = self._application_directory / "user"
        self._workspaces_directory = self._application_directory / "workspaces"
        self._lock_path = self._application_directory / ".catalog.lock"

    def user_directory(self, plugin_id: str, *, create: bool) -> Path | None:
        directory = self._user_directory / plugin_id
        if create:
            _ensure_directory(directory, self._owner)
            return directory
        if not os.path.lexists(directory):
            return None
        _require_directory(directory)
        return directory

    def workspace_access(
        self,
        root: Path,
        plugin_id: str,
        *,
        create: bool,
        exclusive: bool,
    ) -> AbstractContextManager[Path | None]:
        @contextmanager
        def access_directory() -> Iterator[Path | None]:
            if not create and not os.path.lexists(self._application_directory):
                yield None
                return
            with self._lock(exclusive=exclusive or create):
                directory = self._workspace_plugin_directory(
                    root, plugin_id, create=create
                )
                yield directory

        return access_directory()

    def known_roots(self, plugin_id: str) -> tuple[Path, ...]:
        if not os.path.lexists(self._application_directory):
            return ()
        with self._lock(exclusive=False):
            if not os.path.lexists(self._workspaces_directory):
                return ()
            _require_directory(self._workspaces_directory)
            roots: list[Path] = []
            for directory in sorted(
                self._workspaces_directory.iterdir(), key=lambda path: path.name
            ):
                if not directory.is_dir() or directory.is_symlink():
                    raise StateCatalogError(
                        f"invalid workspace catalog entry: {directory}"
                    )
                root = self._read_workspace_metadata(directory)
                plugin_directory = directory / "plugins" / plugin_id
                if os.path.lexists(plugin_directory):
                    _require_directory(plugin_directory)
                    roots.append(root)
            return tuple(sorted(roots, key=os.fspath))

    def destroy_plugin_workspace(self, root: Path, plugin_id: str) -> None:
        if not os.path.lexists(self._application_directory):
            return
        with self._lock(exclusive=True):
            workspace_directory = self._workspace_directory(root)
            if not os.path.lexists(workspace_directory):
                return
            self._validate_workspace_record(workspace_directory, root)
            plugin_directory = workspace_directory / "plugins" / plugin_id
            _remove_path(plugin_directory)

            plugins_directory = workspace_directory / "plugins"
            if not os.path.lexists(plugins_directory):
                _remove_path(workspace_directory)
                return
            _require_directory(plugins_directory)
            if not any(plugins_directory.iterdir()):
                _remove_path(workspace_directory)

    def _workspace_plugin_directory(
        self, root: Path, plugin_id: str, *, create: bool
    ) -> Path | None:
        workspace_directory = self._workspace_directory(root)
        plugin_directory = workspace_directory / "plugins" / plugin_id

        if not os.path.lexists(workspace_directory):
            if not create:
                return None
            _ensure_directory(workspace_directory / "plugins", self._owner)
            self._write_workspace_metadata(workspace_directory, root)
        else:
            self._validate_workspace_record(workspace_directory, root)

        if create:
            _ensure_directory(plugin_directory, self._owner)
            return plugin_directory
        if not os.path.lexists(plugin_directory):
            return None
        _require_directory(plugin_directory)
        return plugin_directory

    def _workspace_directory(self, root: Path) -> Path:
        return self._workspaces_directory / _workspace_digest(root)

    def _write_workspace_metadata(self, directory: Path, root: Path) -> None:
        data = json.dumps(
            {"version": self._SCHEMA_VERSION, "root": os.fspath(root)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _atomic_write(directory / "workspace.json", data, self._owner)

    def _read_workspace_metadata(self, directory: Path) -> Path:
        metadata_path = directory / "workspace.json"
        try:
            raw = _read_bytes_no_follow(metadata_path)
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StateCatalogError(
                f"invalid workspace metadata: {metadata_path}"
            ) from error
        if (
            not isinstance(value, dict)
            or value.get("version") != self._SCHEMA_VERSION
            or not isinstance(value.get("root"), str)
        ):
            raise StateCatalogError(
                f"invalid workspace metadata schema: {metadata_path}"
            )
        root = Path(value["root"])
        if not root.is_absolute() or _workspace_digest(root) != directory.name:
            raise StateCatalogError(
                f"workspace metadata does not match its catalog key: {metadata_path}"
            )
        return root

    def _validate_workspace_record(self, directory: Path, root: Path) -> None:
        _require_directory(directory)
        recorded = self._read_workspace_metadata(directory)
        if recorded != root:
            raise StateCatalogError(f"workspace catalog collision: {directory.name}")
        plugins_directory = directory / "plugins"
        if os.path.lexists(plugins_directory):
            _require_directory(plugins_directory)

    def _lock(self, *, exclusive: bool) -> AbstractContextManager[None]:
        @contextmanager
        def locked() -> Iterator[None]:
            _ensure_directory(self._application_directory, self._owner)
            flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self._lock_path, flags, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                _chown_descriptor(descriptor, self._owner)
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(descriptor, operation)
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

        return locked()


def _resolve_state_owner(
    effective_uid: int,
    effective_gid: int,
    environment: Mapping[str, str],
) -> _StateOwner:
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
        raise RuntimeError(f"state owner UID does not exist: {owner_uid}") from error
    return _StateOwner(owner_uid, owner_gid, Path(account.pw_dir), under_sudo)


def _parse_nonnegative_integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _workspace_digest(root: Path) -> str:
    return hashlib.sha256(os.fsencode(root)).hexdigest()


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str):
        raise TypeError("state filename must be a string")
    if (
        not filename
        or "\0" in filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or Path(filename).is_absolute()
        or (os.altsep is not None and os.altsep in filename)
    ):
        raise ValueError("state filename must be one non-empty path component")
    return filename


def _ensure_directory(directory: Path, owner: _StateOwner) -> None:
    missing: list[Path] = []
    current = directory
    while not os.path.lexists(current):
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    if os.path.lexists(current):
        _require_directory(current)

    for path in reversed(missing):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            _require_directory(path)
            continue
        path.chmod(0o700)
        _chown_path(path, owner)

    _require_directory(directory)


def _require_directory(directory: Path) -> None:
    metadata = directory.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise StateCatalogError(f"state path is not a directory: {directory}")


def _read_bytes_no_follow(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, data: bytes, owner: _StateOwner) -> None:
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
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    if not os.path.lexists(path):
        return
    metadata = path.lstat()
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _chown_path(path: Path, owner: _StateOwner) -> None:
    if os.geteuid() == 0:
        os.chown(path, owner.uid, owner.gid, follow_symlinks=False)


def _chown_descriptor(descriptor: int, owner: _StateOwner) -> None:
    if os.geteuid() == 0:
        os.fchown(descriptor, owner.uid, owner.gid)
