from __future__ import annotations

# Ruff's nested-context rewrite obscures lock ordering in these tests, and child
# process boundaries intentionally report every ordinary exception to the parent.
# ruff: noqa: BLE001, SIM117
import contextlib
import hashlib
import logging
import math
import multiprocessing
import os
import stat
import tempfile
import traceback
import unittest
from collections.abc import Iterator
from multiprocessing.connection import Connection, wait
from pathlib import Path
from unittest.mock import patch

if os.name == "posix":
    import fcntl
else:
    fcntl = None

from engulf.plugin_api import InvocationContextTable, RuntimePluginAPI
from engulf.state import InvocationStateManager
from engulf_api import (
    Invocation,
    LockTimeoutError,
    PluginPhaseError,
    StateCatalogError,
    StateScope,
)


def _make_runtime(
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
) -> tuple[InvocationStateManager, RuntimePluginAPI]:
    invocation = Invocation((), workspace.resolve(), dict(os.environ))
    manager = InvocationStateManager(
        application_id=application_id,
        invocation=invocation,
        workspace_root_resolver=None,
        state_home_resolver=lambda context: state_home,
        environment=dict(os.environ),
    )
    api = RuntimePluginAPI(
        participant_id=plugin_id,
        context_reads=frozenset(),
        context_writes=frozenset(),
        context_table=InvocationContextTable(),
        state_manager=manager,
        diagnostic_logger=logging.getLogger(f"tests.{plugin_id}"),
        elevated=False,
    )
    api.activate("test.preprocess")
    return manager, api


@contextlib.contextmanager
def _active_runtime(
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
) -> Iterator[tuple[InvocationStateManager, RuntimePluginAPI]]:
    manager, api = _make_runtime(state_home, application_id, plugin_id, workspace)
    try:
        yield manager, api
    finally:
        api.deactivate()
        api.close()


def _report_child_error(connection: Connection) -> None:
    connection.send(("error", traceback.format_exc()))


def _transaction_holder(
    connection: Connection,
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
    scope: StateScope,
) -> None:
    try:
        with _active_runtime(state_home, application_id, plugin_id, workspace) as (
            _,
            api,
        ):
            store = api.state(scope)
            with store.transaction():
                connection.send(("acquired",))
                command = connection.recv()
                if command[0] == "write":
                    store.write_text("value", command[1])
            connection.send(("released",))
    except Exception:
        _report_child_error(connection)
    finally:
        connection.close()


def _counter_first(
    connection: Connection,
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
) -> None:
    try:
        with _active_runtime(state_home, application_id, plugin_id, workspace) as (
            _,
            api,
        ):
            store = api.state(StateScope.USER)
            with store.transaction() as locked:
                value = int(locked.read_text("counter"))
                connection.send(("read", value))
                connection.recv()
                locked.write_text("counter", str(value + 1))
            connection.send(("done",))
    except Exception:
        _report_child_error(connection)
    finally:
        connection.close()


def _counter_second(
    connection: Connection,
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
) -> None:
    try:
        with _active_runtime(state_home, application_id, plugin_id, workspace) as (
            _,
            api,
        ):
            store = api.state(StateScope.USER)
            connection.send(("attempting",))
            with store.transaction() as locked:
                value = int(locked.read_text("counter"))
                locked.write_text("counter", str(value + 1))
                connection.send(("acquired", value))
    except Exception:
        _report_child_error(connection)
    finally:
        connection.close()


def _lease_holder(
    connection: Connection,
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
    names: tuple[str, ...],
    start: multiprocessing.synchronize.Event | None = None,
) -> None:
    try:
        with _active_runtime(state_home, application_id, plugin_id, workspace) as (
            _,
            api,
        ):
            if start is not None:
                connection.send(("ready",))
                start.wait()
            with api.leases(names, timeout=3):
                connection.send(("acquired",))
                connection.recv()
            connection.send(("released",))
    except Exception:
        _report_child_error(connection)
    finally:
        connection.close()


def _destroy_workspace(
    connection: Connection,
    state_home: Path,
    application_id: str,
    plugin_id: str,
    workspace: Path,
) -> None:
    try:
        with _active_runtime(state_home, application_id, plugin_id, workspace) as (
            manager,
            api,
        ):
            api.state(StateScope.WORKSPACE).destroy()
        connection.send(("destroying",))
        failures = manager.finalize_destructions()
        connection.send(("destroyed", len(failures)))
    except Exception:
        _report_child_error(connection)
    finally:
        connection.close()


class ConcurrencyTestCase(unittest.TestCase):
    application_id = "engulf-concurrency-tests"
    plugin_id = "tests.concurrency.owner"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.state_home = self.directory / "state"
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir()
        process_start = "fork" if os.name == "posix" else "spawn"
        self.process_context = multiprocessing.get_context(process_start)

    def _start_process(self, target, *args):
        parent, child = self.process_context.Pipe()
        process = self.process_context.Process(target=target, args=(child, *args))
        process.start()
        child.close()
        self.addCleanup(self._cleanup_process, process)
        self.addCleanup(parent.close)
        return process, parent

    @staticmethod
    def _cleanup_process(process) -> None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)

    def _receive(self, connection: Connection, timeout: float = 5):
        self.assertTrue(connection.poll(timeout), "child process did not respond")
        try:
            message = connection.recv()
        except EOFError:
            self.fail("child process exited without a result")
        if message[0] == "error":
            self.fail(message[1])
        return message

    def _holder(
        self,
        *,
        scope: StateScope = StateScope.USER,
        application_id: str | None = None,
        plugin_id: str | None = None,
    ):
        return self._start_process(
            _transaction_holder,
            self.state_home,
            application_id or self.application_id,
            plugin_id or self.plugin_id,
            self.workspace,
            scope,
        )

    def _lease_holder(
        self,
        names: tuple[str, ...],
        *,
        application_id: str | None = None,
        plugin_id: str | None = None,
        start=None,
    ):
        return self._start_process(
            _lease_holder,
            self.state_home,
            application_id or self.application_id,
            plugin_id or self.plugin_id,
            self.workspace,
            names,
            start,
        )

    def _active(self, *, application_id=None, plugin_id=None):
        return _active_runtime(
            self.state_home,
            application_id or self.application_id,
            plugin_id or self.plugin_id,
            self.workspace,
        )

    def test_user_operations_take_shared_and_exclusive_store_locks(self) -> None:
        if fcntl is None:
            self.skipTest("fcntl instrumentation is POSIX-specific")
        with self._active() as (_, api):
            store = api.state(StateScope.USER)
            store.write_text("value", "one")

            with patch("engulf._state_posix.fcntl.flock", wraps=fcntl.flock) as flock:
                self.assertTrue(store.exists("value"))
            shared = [
                call.args[1]
                for call in flock.call_args_list
                if call.args[1] == fcntl.LOCK_SH
            ]
            self.assertGreaterEqual(len(shared), 2)

            with patch("engulf._state_posix.fcntl.flock", wraps=fcntl.flock) as flock:
                store.write_text("value", "two")
            exclusive = [
                call.args[1]
                for call in flock.call_args_list
                if call.args[1] == fcntl.LOCK_EX
            ]
            self.assertGreaterEqual(len(exclusive), 2)

    def test_transactional_counter_updates_do_not_get_lost(self) -> None:
        with self._active() as (_, api):
            api.state(StateScope.USER).write_text("counter", "0")

        first_process, first = self._start_process(
            _counter_first,
            self.state_home,
            self.application_id,
            self.plugin_id,
            self.workspace,
        )
        self.assertEqual(self._receive(first), ("read", 0))
        second_process, second = self._start_process(
            _counter_second,
            self.state_home,
            self.application_id,
            self.plugin_id,
            self.workspace,
        )
        self.assertEqual(self._receive(second), ("attempting",))
        self.assertFalse(second.poll(0.15), "second transaction did not block")

        first.send(("continue",))
        self.assertEqual(self._receive(first), ("done",))
        self.assertEqual(self._receive(second), ("acquired", 1))
        first_process.join(timeout=5)
        second_process.join(timeout=5)
        self.assertEqual(first_process.exitcode, 0)
        self.assertEqual(second_process.exitcode, 0)

        with self._active() as (_, api):
            self.assertEqual(api.state(StateScope.USER).read_text("counter"), "2")

    def test_transaction_exception_releases_lock_without_rollback(self) -> None:
        with self._active() as (_, api):
            store = api.state(StateScope.USER)
            with self.assertRaisesRegex(RuntimeError, "transaction body"):
                with store.transaction() as locked:
                    locked.write_text("value", "committed")
                    raise RuntimeError("transaction body")

            with store.transaction(timeout=0) as locked:
                self.assertEqual(locked.read_text("value"), "committed")

    def test_transaction_timeout_identifies_store(self) -> None:
        process, connection = self._holder()
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active() as (_, api):
            store = api.state(StateScope.USER)
            with self.assertRaisesRegex(
                LockTimeoutError,
                "state transaction timed out.*user store.*tests.concurrency.owner",
            ):
                with store.transaction(timeout=0):
                    pass
        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)

    def test_nested_transactions_and_lock_inversion_are_rejected(self) -> None:
        with self._active() as (_, api):
            user = api.state(StateScope.USER)
            workspace = api.state(StateScope.WORKSPACE)
            with user.transaction():
                with self.assertRaisesRegex(RuntimeError, "nested or overlapping"):
                    with workspace.transaction(timeout=0):
                        pass
                with self.assertRaisesRegex(
                    RuntimeError, "cannot be acquired while a state transaction"
                ):
                    with api.lease("bridge:wan0", timeout=0):
                        pass

            with api.lease("bridge:wan0", timeout=0):
                with workspace.transaction(timeout=0):
                    pass
                with self.assertRaisesRegex(RuntimeError, "nested or overlapping"):
                    with api.lease("bridge:wan1", timeout=0):
                        pass

    def test_workspace_destruction_waits_for_transaction(self) -> None:
        with self._active() as (_, api):
            api.state(StateScope.WORKSPACE).write_text("value", "present")

        holder_process, holder = self._holder(scope=StateScope.WORKSPACE)
        self.assertEqual(self._receive(holder), ("acquired",))
        destroy_process, destroy = self._start_process(
            _destroy_workspace,
            self.state_home,
            self.application_id,
            self.plugin_id,
            self.workspace,
        )
        self.assertEqual(self._receive(destroy), ("destroying",))
        self.assertFalse(destroy.poll(0.15), "workspace destruction did not block")

        holder.send(("release",))
        self.assertEqual(self._receive(holder), ("released",))
        self.assertEqual(self._receive(destroy), ("destroyed", 0))
        holder_process.join(timeout=5)
        destroy_process.join(timeout=5)

        digest = hashlib.sha256(os.fsencode(self.workspace.resolve())).hexdigest()
        record = self.state_home / self.application_id / "workspaces" / digest
        self.assertFalse(record.exists())

    def test_same_lease_serializes_and_different_name_does_not(self) -> None:
        process, connection = self._lease_holder(("docker-image:test",))
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active() as (_, api):
            with self.assertRaises(LockTimeoutError):
                with api.lease("docker-image:test", timeout=0):
                    pass
            with api.lease("docker-image:other", timeout=0):
                pass

        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)
        with self._active() as (_, api):
            with api.lease("docker-image:test", timeout=0):
                pass

    def test_same_lease_contends_across_plugin_ids(self) -> None:
        process, connection = self._lease_holder(
            ("wan-bridge:wan0",), plugin_id="tests.concurrency.first"
        )
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active(plugin_id="tests.concurrency.second") as (_, api):
            with self.assertRaises(LockTimeoutError):
                with api.lease("wan-bridge:wan0", timeout=0):
                    pass
        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)

    def test_same_lease_is_independent_across_application_ids(self) -> None:
        process, connection = self._lease_holder(
            ("wan-bridge:wan0",), application_id="engulf-first-application"
        )
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active(application_id="engulf-second-application") as (_, api):
            with api.lease("wan-bridge:wan0", timeout=0):
                pass
        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)

    def test_lease_names_are_case_sensitive(self) -> None:
        process, connection = self._lease_holder(("wan-bridge:WAN0",))
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active() as (_, api):
            with api.lease("wan-bridge:wan0", timeout=0):
                pass
        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)

    def test_multi_lease_order_is_deterministic(self) -> None:
        start = self.process_context.Event()
        first_process, first = self._lease_holder(("b", "a"), start=start)
        second_process, second = self._lease_holder(("a", "b"), start=start)
        self.assertEqual(self._receive(first), ("ready",))
        self.assertEqual(self._receive(second), ("ready",))
        start.set()

        ready = wait((first, second), timeout=5)
        self.assertTrue(ready, "neither multi-lease caller acquired its locks")
        winner = ready[0]
        loser = second if winner is first else first
        self.assertEqual(self._receive(winner), ("acquired",))
        self.assertFalse(loser.poll(0.15), "both callers held the same leases")
        winner.send(("release",))
        self.assertEqual(self._receive(winner), ("released",))
        self.assertEqual(self._receive(loser), ("acquired",))
        loser.send(("release",))
        self.assertEqual(self._receive(loser), ("released",))
        first_process.join(timeout=5)
        second_process.join(timeout=5)
        self.assertEqual(first_process.exitcode, 0)
        self.assertEqual(second_process.exitcode, 0)

    def test_partial_multi_lease_is_released_after_timeout(self) -> None:
        process, connection = self._lease_holder(("b",))
        self.assertEqual(self._receive(connection), ("acquired",))
        with self._active() as (_, api):
            with self.assertRaisesRegex(LockTimeoutError, "resource lease.*'b'"):
                with api.leases(("a", "b"), timeout=0):
                    pass
            with api.lease("a", timeout=0):
                pass
        connection.send(("release",))
        self.assertEqual(self._receive(connection), ("released",))
        process.join(timeout=5)

    def test_process_termination_releases_lease(self) -> None:
        process, connection = self._lease_holder(("vrnetlab-builder:test",))
        self.assertEqual(self._receive(connection), ("acquired",))
        process.terminate()
        process.join(timeout=5)
        self.assertFalse(process.is_alive())

        with self._active() as (_, api):
            with api.lease("vrnetlab-builder:test", timeout=1):
                pass

    def test_invalid_names_timeouts_and_context_reuse_are_rejected(self) -> None:
        with self._active() as (_, api):
            store = api.state(StateScope.USER)
            for name in ("", "nul\0name"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    api.lease(name)
            with self.assertRaises(TypeError):
                api.lease(3)
            with self.assertRaises(TypeError):
                api.leases("not-an-iterable-of-names")
            with self.assertRaises(TypeError):
                api.leases(3)
            with self.assertRaises(ValueError):
                api.leases(("valid", ""))

            for timeout in (True, -1, math.nan, math.inf, -math.inf):
                with self.subTest(timeout=timeout):
                    with self.assertRaises((TypeError, ValueError)):
                        store.transaction(timeout=timeout)
                    with self.assertRaises((TypeError, ValueError)):
                        api.lease("valid", timeout=timeout)
            with self.assertRaises(TypeError):
                store.transaction(timeout="1")

            transaction = store.transaction(timeout=0)
            with transaction:
                pass
            with self.assertRaisesRegex(RuntimeError, "entered only once"):
                with transaction:
                    pass

            leases = api.leases(("duplicate", "duplicate"), timeout=0)
            with leases:
                pass
            with self.assertRaisesRegex(RuntimeError, "entered only once"):
                with leases:
                    pass

    def test_capabilities_are_invocation_bound_and_hook_cleanup_releases_locks(
        self,
    ) -> None:
        manager, api = _make_runtime(
            self.state_home, self.application_id, self.plugin_id, self.workspace
        )
        store = api.state(StateScope.USER)
        transaction = store.transaction(timeout=0)
        lease = api.lease("cleanup:test", timeout=0)
        later_transaction = store.transaction(timeout=0)
        later_lease = api.lease("cleanup:later", timeout=0)
        api.deactivate()

        with self.assertRaises(PluginPhaseError):
            store.transaction()
        with self.assertRaises(PluginPhaseError):
            transaction.__enter__()
        with self.assertRaises(PluginPhaseError):
            api.lease("cleanup:test")
        with self.assertRaises(PluginPhaseError):
            lease.__enter__()

        api.activate("test.postprocess")
        with self.assertRaisesRegex(PluginPhaseError, "earlier callback"):
            later_transaction.__enter__()
        with self.assertRaisesRegex(PluginPhaseError, "earlier callback"):
            later_lease.__enter__()
        api.deactivate()
        api.close()
        self.assertEqual(manager.finalize_destructions(), ())

        manager, api = _make_runtime(
            self.state_home, self.application_id, self.plugin_id, self.workspace
        )
        leaked_lease = api.lease("cleanup:test", timeout=0)
        leaked_lease.__enter__()
        api.deactivate()
        api.close()

        with self._active(plugin_id="tests.concurrency.other") as (_, other):
            with other.lease("cleanup:test", timeout=0):
                pass

        manager, api = _make_runtime(
            self.state_home, self.application_id, self.plugin_id, self.workspace
        )
        leaked_transaction = api.state(StateScope.USER).transaction(timeout=0)
        leaked_transaction.__enter__()
        api.deactivate()
        api.close()

        with self._active() as (_, other):
            with other.state(StateScope.USER).transaction(timeout=0):
                pass

    def test_lock_files_are_persistent_private_and_owned(self) -> None:
        with self._active() as (_, api):
            with api.lease("permissions:test", timeout=0):
                pass
            with api.state(StateScope.USER).transaction(timeout=0):
                pass
            with api.state(StateScope.WORKSPACE).transaction(timeout=0):
                pass

        application = self.state_home / self.application_id
        lock_files = sorted(application.rglob("*.lock"))
        self.assertGreaterEqual(len(lock_files), 3)
        for path in lock_files:
            with self.subTest(path=path):
                metadata = path.stat()
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
                    self.assertEqual(metadata.st_uid, os.geteuid())
                    self.assertEqual(metadata.st_gid, os.getegid())
        for path in (
            application,
            *[item for item in application.rglob("*") if item.is_dir()],
        ):
            with self.subTest(path=path):
                metadata = path.stat()
                self.assertTrue(path.is_dir())
                self.assertFalse(path.is_symlink())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o700)
                    self.assertEqual(metadata.st_uid, os.geteuid())
                    self.assertEqual(metadata.st_gid, os.getegid())

    def test_symlinked_lock_file_and_directory_are_rejected(self) -> None:
        with self._active() as (_, api):
            with api.lease("symlink:file", timeout=0):
                pass

        lease_files = list(
            (self.state_home / self.application_id / ".locks").rglob("*.lock")
        )
        self.assertEqual(len(lease_files), 1)
        lease_file = lease_files[0]
        lease_file.unlink()
        target = self.directory / "target"
        target.write_text("target", encoding="utf-8")
        try:
            lease_file.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")
        with self._active() as (_, api):
            with self.assertRaisesRegex(StateCatalogError, "cannot be a .*link"):
                with api.lease("symlink:file", timeout=0):
                    pass

        application_id = "engulf-symlink-directory-test"
        application = self.state_home / application_id
        application.mkdir(mode=0o700)
        lock_target = self.directory / "lock-target"
        lock_target.mkdir()
        try:
            (application / ".locks").symlink_to(
                lock_target,
                target_is_directory=True,
            )
        except OSError as error:
            self.skipTest(f"directory symbolic links are unavailable: {error}")
        with self._active(application_id=application_id) as (_, api):
            with self.assertRaisesRegex(StateCatalogError, "not a directory"):
                with api.lease("symlink:directory", timeout=0):
                    pass


if __name__ == "__main__":
    unittest.main()
