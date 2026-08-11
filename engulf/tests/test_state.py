from __future__ import annotations

import contextlib
import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engulf_api import PluginPhaseError, StateCatalogError, StateScope
from support import CoreTestPlugin, PassGoal

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    Application,
    StateHomeContext,
    WorkspaceContext,
)


class StatePlugin(CoreTestPlugin):
    def __init__(self, plugin_id: str, *, before=None, after=None) -> None:
        self.plugin_id = plugin_id
        self.before_action = before
        self.after_action = after

    def help(self, api) -> str:
        del api
        return ""

    def before_goal(self, event, api):
        if self.before_action is not None:
            self.before_action(event, api)

    def after_goal(self, event, result, api):
        if self.after_action is not None:
            self.after_action(event, api)
        return result


_DEFAULT_STATE_HOME = object()


class StateTestCase(unittest.TestCase):
    application_id = "engulf-state-tests"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        self.state_home = self.directory / "state"
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir()

    def make_application(
        self,
        *plugins: CoreTestPlugin,
        binary: str | os.PathLike[str] = "/bin/true",
        workspace_root_resolver=None,
        state_home_resolver=_DEFAULT_STATE_HOME,
    ) -> Application:
        if state_home_resolver is _DEFAULT_STATE_HOME:
            state_home_resolver = lambda context: self.state_home
        with patch(
            "engulf.application.load_directory_plugins", return_value=tuple(plugins)
        ):
            return Application(
                self.application_id,
                PassGoal(exit_code=1 if os.fspath(binary) == "/bin/false" else 0),
                display_name="engulf-state-tests",
                vendor="Engulf Tests",
                product="State Tests",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
                workspace_root_resolver=workspace_root_resolver,
                state_home_resolver=state_home_resolver,
            )

    @staticmethod
    def run_in(application: Application, workspace: Path, args=()) -> int:
        with patch("engulf.application.Path.cwd", return_value=workspace):
            return application.run(args)

    def workspace_record(self, workspace: Path) -> Path:
        digest = hashlib.sha256(os.fsencode(workspace.resolve())).hexdigest()
        return self.state_home / self.application_id / "workspaces" / digest

    def test_state_is_lazy_scoped_managed_and_call_bound(self) -> None:
        def inspect_absent_state(event, api) -> None:
            self.assertFalse(api.state(StateScope.USER).exists("missing"))
            self.assertFalse(api.state(StateScope.WORKSPACE).exists("missing"))
            self.assertEqual(api.known_workspaces(), ())

        no_state = StatePlugin("tests.state.no_state", before=inspect_absent_state)
        self.assertEqual(
            self.run_in(self.make_application(no_state), self.workspace), 0
        )
        self.assertFalse((self.state_home / self.application_id / "user").exists())
        self.assertFalse(
            (self.state_home / self.application_id / "workspaces").exists()
        )

        plugin_id = "tests.state.managed"
        retained = []

        def write_state(event, api) -> None:
            user = api.state(StateScope.USER)
            workspace = api.state(StateScope.WORKSPACE)
            retained.extend((user, workspace))

            self.assertEqual(workspace.root, self.workspace.resolve())
            self.assertFalse(user.exists("user.txt"))
            self.assertFalse(workspace.exists("workspace.bin"))
            user.write_text("user.txt", "user value")
            workspace.write_bytes("workspace.bin", b"workspace value")
            workspace.write_text("delete.txt", "temporary")
            workspace.delete("delete.txt")
            workspace.delete("missing.txt", missing_ok=True)

            self.assertEqual(user.read_text("user.txt"), "user value")
            self.assertEqual(workspace.read_bytes("workspace.bin"), b"workspace value")
            self.assertFalse(workspace.exists("delete.txt"))
            self.assertEqual(user.path("user.txt").name, "user.txt")
            for filename in ("", ".", "..", "../escape", "a/b", "a\0b"):
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    user.path(filename)
            with self.assertRaises(TypeError):
                user.path(3)

        def read_state(event, api) -> None:
            self.assertIs(api.state(StateScope.USER), retained[0])
            self.assertIs(api.state(StateScope.WORKSPACE), retained[1])
            self.assertEqual(retained[0].read_text("user.txt"), "user value")
            self.assertEqual(
                retained[1].read_bytes("workspace.bin"), b"workspace value"
            )

        plugin = StatePlugin(plugin_id, before=write_state, after=read_state)
        self.assertEqual(self.run_in(self.make_application(plugin), self.workspace), 0)

        user_directory = self.state_home / self.application_id / "user" / plugin_id
        workspace_directory = (
            self.workspace_record(self.workspace) / "plugins" / plugin_id
        )
        self.assertEqual(
            (user_directory / "user.txt").read_text(encoding="utf-8"),
            "user value",
        )
        self.assertEqual(
            (workspace_directory / "workspace.bin").read_bytes(),
            b"workspace value",
        )
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(user_directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(workspace_directory.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((user_directory / "user.txt").stat().st_mode), 0o600
            )
            self.assertEqual(
                stat.S_IMODE((workspace_directory / "workspace.bin").stat().st_mode),
                0o600,
            )
        for store in retained:
            with self.assertRaises(PluginPhaseError):
                store.exists("user.txt")

    def test_known_workspaces_persist_and_are_private_to_the_plugin(self) -> None:
        owner_id = "tests.state.owner"
        other_id = "tests.state.other"
        workspace_a = self.directory / "workspace-a"
        workspace_b = self.directory / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        writer = StatePlugin(
            owner_id,
            before=lambda event, api: api.state(StateScope.WORKSPACE).write_text(
                "marker", "from-a"
            ),
        )
        self.assertEqual(self.run_in(self.make_application(writer), workspace_a), 0)
        workspace_a.rmdir()

        observed = []

        def inspect_owner(event, api) -> None:
            workspaces = api.known_workspaces()
            observed.extend(workspaces)
            self.assertEqual(
                tuple(workspace.root for workspace in workspaces),
                (workspace_a.resolve(),),
            )
            self.assertEqual(workspaces[0].read_text("marker"), "from-a")

        def inspect_other(event, api) -> None:
            self.assertEqual(api.known_workspaces(), ())

        reader = StatePlugin(owner_id, before=inspect_owner)
        other = StatePlugin(other_id, before=inspect_other)
        self.assertEqual(
            self.run_in(self.make_application(reader, other), workspace_b), 0
        )
        with self.assertRaises(PluginPhaseError):
            observed[0].read_text("marker")

    def test_destroy_is_deferred_idempotent_and_prunes_the_last_plugin(self) -> None:
        first_id = "tests.state.cleanup.first"
        second_id = "tests.state.cleanup.second"

        def seed(filename: str):
            return lambda event, api: api.state(StateScope.WORKSPACE).write_text(
                filename, filename
            )

        first = StatePlugin(first_id, before=seed("first"))
        second = StatePlugin(second_id, before=seed("second"))
        self.assertEqual(
            self.run_in(self.make_application(first, second), self.workspace), 0
        )
        record = self.workspace_record(self.workspace)

        def destroy_first(event, api) -> None:
            workspace = api.state(StateScope.WORKSPACE)
            workspace.destroy()
            workspace.destroy()

        def verify_deferred(event, api) -> None:
            workspace = api.state(StateScope.WORKSPACE)
            self.assertEqual(workspace.read_text("first"), "first")
            self.assertEqual(len(api.known_workspaces()), 1)

        first = StatePlugin(first_id, before=destroy_first, after=verify_deferred)
        second = StatePlugin(second_id)
        self.assertEqual(
            self.run_in(self.make_application(first, second), self.workspace), 0
        )
        self.assertFalse((record / "plugins" / first_id).exists())
        self.assertTrue((record / "plugins" / second_id).is_dir())
        self.assertTrue(record.is_dir())

        second = StatePlugin(
            second_id,
            after=lambda event, api: api.state(StateScope.WORKSPACE).destroy(),
        )
        self.assertEqual(self.run_in(self.make_application(second), self.workspace), 0)
        self.assertFalse(record.exists())

    def test_cleanup_commits_after_binary_and_postprocess_failures(self) -> None:
        plugin_id = "tests.state.cleanup.outcomes"

        def seed() -> None:
            plugin = StatePlugin(
                plugin_id,
                before=lambda event, api: api.state(StateScope.WORKSPACE).write_text(
                    "marker", "value"
                ),
            )
            self.assertEqual(
                self.run_in(self.make_application(plugin), self.workspace), 0
            )

        destroy = lambda event, api: api.state(StateScope.WORKSPACE).destroy()

        seed()
        plugin = StatePlugin(plugin_id, before=destroy)
        result = self.run_in(
            self.make_application(plugin, binary="/bin/false"), self.workspace
        )
        self.assertEqual(result, 1)
        self.assertFalse(self.workspace_record(self.workspace).exists())

        seed()

        def fail_after(event, api) -> None:
            raise RuntimeError("postprocess failed")

        plugin = StatePlugin(plugin_id, before=destroy, after=fail_after)
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.run_in(self.make_application(plugin), self.workspace)
        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertFalse(self.workspace_record(self.workspace).exists())

    def test_all_cleanup_is_attempted_and_failure_takes_precedence(self) -> None:
        attempted = []

        def destroy(event, api) -> None:
            workspace = api.state(StateScope.WORKSPACE)
            workspace.destroy()
            workspace.destroy()

        plugins = (
            StatePlugin("tests.state.cleanup.alpha", before=destroy),
            StatePlugin("tests.state.cleanup.beta", before=destroy),
        )

        def fail_cleanup(catalog, root, plugin_id) -> None:
            attempted.append((root, plugin_id))
            raise OSError(f"cannot remove {plugin_id}")

        with (
            patch(
                "engulf.state._StateCatalog.destroy_plugin_workspace",
                autospec=True,
                side_effect=fail_cleanup,
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = self.run_in(
                self.make_application(*plugins, binary="/bin/false"), self.workspace
            )

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(
            [plugin_id for _, plugin_id in attempted],
            [plugin.plugin_id for plugin in plugins],
        )
        self.assertEqual(len(attempted), 2)
        self.assertIn("workspace state cleanup failed", errors.getvalue())

    def test_application_resolvers_receive_stable_call_context(self) -> None:
        lab = self.workspace / "lab"
        lab.mkdir()
        workspace_contexts = []
        state_home_contexts = []

        def resolve_workspace(context: WorkspaceContext) -> str:
            workspace_contexts.append(context)
            return "lab"

        def resolve_state_home(context: StateHomeContext) -> Path:
            state_home_contexts.append(context)
            return self.state_home

        def inspect(event, api) -> None:
            first = api.state(StateScope.WORKSPACE)
            second = api.state(StateScope.WORKSPACE)
            self.assertIs(first, second)
            self.assertEqual(first.root, lab.resolve())
            first.write_text("marker", "value")
            api.state(StateScope.USER).write_text("user", "value")

        plugin = StatePlugin("tests.state.resolvers", before=inspect)
        engulf = self.make_application(
            plugin,
            workspace_root_resolver=resolve_workspace,
            state_home_resolver=resolve_state_home,
        )
        self.assertEqual(self.run_in(engulf, self.workspace, ("deploy", "--flag")), 0)

        self.assertEqual(len(workspace_contexts), 1)
        workspace_context = workspace_contexts[0]
        self.assertEqual(workspace_context.application_id, self.application_id)
        self.assertEqual(workspace_context.arguments, ("deploy", "--flag"))
        self.assertEqual(workspace_context.cwd, self.workspace.resolve())
        self.assertEqual(len(state_home_contexts), 1)
        state_home_context = state_home_contexts[0]
        self.assertEqual(state_home_context.application_id, self.application_id)
        self.assertTrue(state_home_context.owner_id)
        if os.name == "posix":
            self.assertEqual(
                state_home_context.owner_id,
                f"posix:{os.geteuid()}:{os.getegid()}",
            )
        self.assertTrue(state_home_context.owner_home.is_absolute())
        self.assertIsInstance(state_home_context.elevated, bool)

    @unittest.skipUnless(os.name == "posix", "sudo ownership is POSIX-specific")
    def test_sudo_defaults_to_the_invoking_users_state_home(self) -> None:
        plugin_id = "tests.state.sudo"
        owner_home = self.directory / "owner-home"
        owner_home.mkdir()
        ignored_xdg = self.directory / "root-xdg"
        account = SimpleNamespace(pw_dir=str(owner_home), pw_gid=2345)
        plugin = StatePlugin(
            plugin_id,
            before=lambda event, api: api.state(StateScope.USER).write_text(
                "marker", "value"
            ),
        )
        engulf = self.make_application(plugin, state_home_resolver=None)

        with (
            patch.dict(
                os.environ,
                {
                    "SUDO_UID": "1234",
                    "SUDO_GID": "3456",
                    "XDG_STATE_HOME": str(ignored_xdg),
                },
                clear=False,
            ),
            patch("engulf._state_posix.os.geteuid", return_value=0),
            patch("engulf._state_posix.os.getegid", return_value=0),
            patch("engulf._state_posix.pwd.getpwuid", return_value=account),
            patch("engulf._state_posix._chown_path"),
            patch("engulf._state_posix._chown_descriptor"),
        ):
            result = self.run_in(engulf, self.workspace)

        self.assertEqual(result, 0)
        expected = (
            owner_home
            / ".local"
            / "state"
            / self.application_id
            / "user"
            / plugin_id
            / "marker"
        )
        self.assertEqual(expected.read_text(encoding="utf-8"), "value")
        self.assertFalse(ignored_xdg.exists())

    def test_invalid_catalog_metadata_is_reported(self) -> None:
        plugin_id = "tests.state.catalog"
        writer = StatePlugin(
            plugin_id,
            before=lambda event, api: api.state(StateScope.WORKSPACE).write_text(
                "marker", "value"
            ),
        )
        self.assertEqual(self.run_in(self.make_application(writer), self.workspace), 0)
        metadata = self.workspace_record(self.workspace) / "workspace.json"
        metadata.write_text('{"root":"/wrong","version":1}', encoding="utf-8")

        def inspect(event, api) -> None:
            with self.assertRaises(StateCatalogError):
                api.known_workspaces()

        reader = StatePlugin(plugin_id, before=inspect)
        self.assertEqual(self.run_in(self.make_application(reader), self.workspace), 0)

    def test_constructor_rejects_non_callable_resolvers(self) -> None:
        with self.assertRaises(TypeError):
            self.make_application(workspace_root_resolver=3)
        with self.assertRaises(TypeError):
            self.make_application(state_home_resolver=3)


if __name__ == "__main__":
    unittest.main()
