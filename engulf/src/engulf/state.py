from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from engulf_api import (
    Invocation,
    StateCatalogError,
    StateStore,
    WorkspaceState,
)

from ._state_platform import _HeldFileLock, _StateOwner, get_state_platform


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Inputs available when an application resolves a workspace root."""

    application_id: str
    invocation: Invocation

    @property
    def cwd(self) -> Path:
        return self.invocation.cwd

    @property
    def arguments(self) -> tuple[str, ...]:
        return self.invocation.arguments


type WorkspaceRootResolver = Callable[[WorkspaceContext], str | os.PathLike[str]]


@dataclass(frozen=True, slots=True)
class StateHomeContext:
    """Identity available when an application selects its central state home."""

    application_id: str
    owner_id: str
    owner_home: Path
    elevated: bool


type StateHomeResolver = Callable[[StateHomeContext], str | os.PathLike[str]]


@dataclass(frozen=True, slots=True)
class WorkspaceCleanupFailure:
    root: Path
    plugin_id: str
    error: Exception


class InvocationStateManager:
    """Shared state resolution and deferred cleanup for one invocation."""

    def __init__(
        self,
        *,
        application_id: str,
        invocation: Invocation,
        workspace_root_resolver: WorkspaceRootResolver | None,
        state_home_resolver: StateHomeResolver | None,
        environment: Mapping[str, str],
    ) -> None:
        if not isinstance(invocation, Invocation):
            raise TypeError("invocation must be an Invocation")
        self._application_id = application_id
        self._workspace_context = WorkspaceContext(application_id, invocation)
        self._workspace_root_resolver = workspace_root_resolver
        self._state_home_resolver = state_home_resolver
        self._environment = environment
        self._platform = get_state_platform()
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
            self._owner = self._platform.resolve_owner(self._environment)
        return self._owner

    def user_directory(self, plugin_id: str, *, create: bool) -> Path | None:
        return self._get_catalog().user_directory(plugin_id, create=create)

    def user_store_lock(
        self,
        plugin_id: str,
        *,
        exclusive: bool,
        timeout: float | None,
        operation: str,
    ) -> AbstractContextManager[None]:
        return self._get_catalog().store_lock(
            scope="user",
            plugin_id=plugin_id,
            root=None,
            exclusive=exclusive,
            timeout=timeout,
            operation=operation,
        )

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

    def workspace_store_lock(
        self,
        root: Path,
        plugin_id: str,
        *,
        exclusive: bool,
        timeout: float | None,
        operation: str,
    ) -> AbstractContextManager[None]:
        return self._get_catalog().store_lock(
            scope="workspace",
            plugin_id=plugin_id,
            root=root,
            exclusive=exclusive,
            timeout=timeout,
            operation=operation,
        )

    def resource_leases(
        self,
        names: tuple[str, ...],
        *,
        timeout: float | None,
    ) -> AbstractContextManager[None]:
        return self._get_catalog().resource_leases(names, timeout=timeout)

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
            path = self._workspace_context.invocation.cwd / path
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
            owner_id=owner.identifier,
            owner_home=owner.home,
            elevated=owner.elevated,
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

        return self._platform.default_state_home(owner, self._environment)


class RuntimeStateStore(StateStore):
    def __init__(
        self,
        backend: _UserStoreBackend | _WorkspaceStoreBackend,
        require_active: Callable[[str], None],
        transaction_factory: Callable[
            [RuntimeStateStore, float | None], AbstractContextManager[StateStore]
        ],
    ) -> None:
        self._backend = backend
        self._require_active = require_active
        self._transaction_factory = transaction_factory
        self._transaction_active = False

    @property
    def directory(self) -> Path:
        self._require_active("state.directory")
        with self._access(create=True, exclusive=True) as directory:
            assert directory is not None
            return directory

    def path(self, filename: str) -> Path:
        self._require_active("state.path")
        name = _validate_filename(filename)
        with self._access(create=True, exclusive=True) as directory:
            assert directory is not None
            return directory / name

    def exists(self, filename: str) -> bool:
        self._require_active("state.exists")
        name = _validate_filename(filename)
        with self._access(create=False, exclusive=False) as directory:
            if directory is None:
                return False
            path = directory / name
            if self._backend.owner.platform.is_link(path):
                raise StateCatalogError(f"state file cannot be a link: {path}")
            return path.exists()

    def read_bytes(self, filename: str) -> bytes:
        self._require_active("state.read_bytes")
        name = _validate_filename(filename)
        with self._access(create=False, exclusive=False) as directory:
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
        with self._access(create=True, exclusive=True) as directory:
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
        with self._access(create=False, exclusive=True) as directory:
            if directory is None:
                if missing_ok:
                    return
                raise FileNotFoundError(filename)
            (directory / name).unlink(missing_ok=missing_ok)

    def transaction(
        self,
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[StateStore]:
        self._require_active("state.transaction")
        return self._transaction_factory(self, _validate_lock_timeout(timeout))

    def _access(
        self,
        *,
        create: bool,
        exclusive: bool,
    ) -> AbstractContextManager[Path | None]:
        return self._backend.access(
            create=create,
            exclusive=exclusive,
            store_locked=self._transaction_active,
        )

    def _transaction_lock(self, timeout: float | None) -> AbstractContextManager[None]:
        return self._backend.lock(
            exclusive=True,
            timeout=timeout,
            operation="state transaction",
        )

    def _set_transaction_active(self, active: bool) -> None:
        self._transaction_active = active


class RuntimeWorkspaceState(RuntimeStateStore, WorkspaceState):
    def __init__(
        self,
        backend: _WorkspaceStoreBackend,
        require_active: Callable[[str], None],
        transaction_factory: Callable[
            [RuntimeStateStore, float | None], AbstractContextManager[StateStore]
        ],
    ) -> None:
        super().__init__(backend, require_active, transaction_factory)
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
    def __init__(self, manager: InvocationStateManager, plugin_id: str) -> None:
        self.manager = manager
        self.plugin_id = plugin_id

    @property
    def owner(self) -> _StateOwner:
        return self.manager.owner

    def access(
        self, *, create: bool, exclusive: bool, store_locked: bool
    ) -> AbstractContextManager[Path | None]:
        @contextmanager
        def access_directory() -> Iterator[Path | None]:
            lock = (
                nullcontext()
                if store_locked
                else self.lock(
                    exclusive=exclusive or create,
                    timeout=None,
                    operation="state operation",
                )
            )
            with lock:
                yield self.manager.user_directory(self.plugin_id, create=create)

        return access_directory()

    def lock(
        self,
        *,
        exclusive: bool,
        timeout: float | None,
        operation: str,
    ) -> AbstractContextManager[None]:
        return self.manager.user_store_lock(
            self.plugin_id,
            exclusive=exclusive,
            timeout=timeout,
            operation=operation,
        )


class _WorkspaceStoreBackend:
    def __init__(
        self, manager: InvocationStateManager, root: Path, plugin_id: str
    ) -> None:
        self.manager = manager
        self.root = root
        self.plugin_id = plugin_id

    @property
    def owner(self) -> _StateOwner:
        return self.manager.owner

    def access(
        self, *, create: bool, exclusive: bool, store_locked: bool
    ) -> AbstractContextManager[Path | None]:
        @contextmanager
        def access_directory() -> Iterator[Path | None]:
            lock = (
                nullcontext()
                if store_locked
                else self.lock(
                    exclusive=exclusive or create,
                    timeout=None,
                    operation="state operation",
                )
            )
            with (
                lock,
                self.manager.workspace_access(
                    self.root,
                    self.plugin_id,
                    create=create,
                    exclusive=exclusive,
                ) as directory,
            ):
                yield directory

        return access_directory()

    def lock(
        self,
        *,
        exclusive: bool,
        timeout: float | None,
        operation: str,
    ) -> AbstractContextManager[None]:
        return self.manager.workspace_store_lock(
            self.root,
            self.plugin_id,
            exclusive=exclusive,
            timeout=timeout,
            operation=operation,
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
        owner_directory = hashlib.sha256(owner.identifier.encode("utf-8")).hexdigest()
        self._owner_locks_directory = (
            self._application_directory / ".locks" / owner_directory
        )
        self._store_locks_directory = self._owner_locks_directory / "stores"
        self._lease_locks_directory = self._owner_locks_directory / "leases"

    def user_directory(self, plugin_id: str, *, create: bool) -> Path | None:
        with self._lock(exclusive=create):
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
                try:
                    _require_directory(directory)
                except (OSError, StateCatalogError) as error:
                    raise StateCatalogError(
                        f"invalid workspace catalog entry: {directory}"
                    ) from error
                root = self._read_workspace_metadata(directory)
                plugin_directory = directory / "plugins" / plugin_id
                if os.path.lexists(plugin_directory):
                    _require_directory(plugin_directory)
                    roots.append(root)
            return tuple(sorted(roots, key=os.fspath))

    def destroy_plugin_workspace(self, root: Path, plugin_id: str) -> None:
        if not os.path.lexists(self._application_directory):
            return
        with (
            self.store_lock(
                scope="workspace",
                plugin_id=plugin_id,
                root=root,
                exclusive=True,
                timeout=None,
                operation="workspace destruction",
            ),
            self._lock(exclusive=True),
        ):
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

    def store_lock(
        self,
        *,
        scope: str,
        plugin_id: str,
        root: Path | None,
        exclusive: bool,
        timeout: float | None,
        operation: str,
    ) -> AbstractContextManager[None]:
        if scope == "user":
            if root is not None:
                raise AssertionError("user store locks cannot have a workspace root")
            identity = f"user\0{plugin_id}".encode()
            scope_directory = "user"
            store_description = f"user store for plugin {plugin_id!r}"
        elif scope == "workspace":
            if root is None:
                raise AssertionError("workspace store locks require a workspace root")
            identity = b"workspace\0" + os.fsencode(root) + b"\0" + plugin_id.encode()
            scope_directory = "workspace"
            store_description = (
                f"workspace store for plugin {plugin_id!r} at {os.fspath(root)!r}"
            )
        else:
            raise AssertionError(f"unknown state scope: {scope}")

        digest = hashlib.sha256(identity).hexdigest()
        path = self._store_locks_directory / scope_directory / f"{digest}.lock"
        timeout_message = (
            f"{operation} timed out for {store_description} "
            f"in application {self._application_id!r} at "
            f"{os.fspath(self._state_home)!r} as owner "
            f"{self._owner.identifier!r}"
        )
        return _file_lock_context(
            path,
            owner=self._owner,
            exclusive=exclusive,
            timeout=timeout,
            timeout_message=timeout_message,
        )

    def resource_leases(
        self,
        names: tuple[str, ...],
        *,
        timeout: float | None,
    ) -> AbstractContextManager[None]:
        @contextmanager
        def acquire_all() -> Iterator[None]:
            deadline = _timeout_deadline(timeout)
            acquired: list[_HeldFileLock] = []
            try:
                for name in names:
                    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
                    path = self._lease_locks_directory / f"{digest}.lock"
                    message = (
                        f"resource lease timed out for {name!r} in application "
                        f"{self._application_id!r} at {os.fspath(self._state_home)!r} "
                        f"as owner {self._owner.identifier!r}"
                    )
                    acquired.append(
                        _acquire_file_lock(
                            path,
                            owner=self._owner,
                            exclusive=True,
                            deadline=deadline,
                            timeout_message=message,
                        )
                    )
                yield
            finally:
                _release_file_locks(reversed(acquired))

        return acquire_all()

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
        return _file_lock_context(
            self._lock_path,
            owner=self._owner,
            exclusive=exclusive,
            timeout=None,
            timeout_message="internal state catalog lock timed out",
        )


def _validate_lock_timeout(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("lock timeout must be a number or None")
    try:
        normalized = float(timeout)
    except OverflowError as error:
        raise ValueError("lock timeout must be finite") from error
    if not math.isfinite(normalized):
        raise ValueError("lock timeout must be finite")
    if normalized < 0:
        raise ValueError("lock timeout cannot be negative")
    return normalized


def _timeout_deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return time.monotonic() + timeout


def _file_lock_context(
    path: Path,
    *,
    owner: _StateOwner,
    exclusive: bool,
    timeout: float | None,
    timeout_message: str,
) -> AbstractContextManager[None]:
    @contextmanager
    def locked() -> Iterator[None]:
        lock = _acquire_file_lock(
            path,
            owner=owner,
            exclusive=exclusive,
            deadline=_timeout_deadline(timeout),
            timeout_message=timeout_message,
        )
        try:
            yield
        finally:
            lock.release()

    return locked()


def _acquire_file_lock(
    path: Path,
    *,
    owner: _StateOwner,
    exclusive: bool,
    deadline: float | None,
    timeout_message: str,
) -> _HeldFileLock:
    return owner.platform.acquire_file_lock(
        path,
        owner=owner,
        exclusive=exclusive,
        deadline=deadline,
        timeout_message=timeout_message,
    )


def _release_file_locks(locks: Iterable[_HeldFileLock]) -> None:
    first_error: BaseException | None = None
    for lock in locks:
        try:
            lock.release()
        except BaseException as error:  # noqa: BLE001 - close every descriptor.
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


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
    owner.platform.ensure_directory(directory, owner)


def _require_directory(directory: Path) -> None:
    get_state_platform().require_directory(directory)


def _read_bytes_no_follow(path: Path) -> bytes:
    return get_state_platform().read_bytes_no_follow(path)


def _atomic_write(path: Path, data: bytes, owner: _StateOwner) -> None:
    owner.platform.atomic_write(path, data, owner)


def _remove_path(path: Path) -> None:
    get_state_platform().remove_path(path)
