from __future__ import annotations

import tempfile
import unittest
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf.plugin_loader import EntryPointIndex
from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    Invocation,
    Plugin,
)

from engulf import (
    Application,
    GoalPrivilegeError,
    goal_privilege_opt_in_entry_point_group,
)

REQUIREMENT = GoalRequirement("tests.privilege.goal", 1)


class PrivilegeGoal(Goal[None]):
    _contract = GoalContract(REQUIREMENT, Plugin)

    def __init__(self) -> None:
        self.setup_count = 0

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def setup(self, api) -> None:
        del api
        self.setup_count += 1

    def achieve(self, invocation: Invocation, api: GoalAPI) -> GoalResult[None]:
        del invocation, api
        return GoalResult.completed(None)


class ChildPrivilegeGoal(PrivilegeGoal):
    pass


class _Distribution:
    def __init__(self, paths: tuple[Path, ...] | None) -> None:
        self.files = (
            None
            if paths is None
            else tuple(str(index) for index, _ in enumerate(paths))
        )
        self._paths = paths
        self.name = "tests-privilege-goal"
        self.version = "1"

    def locate_file(self, record: str) -> Path:
        assert self._paths is not None
        return self._paths[int(record)]


class GoalPrivilegeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)
        self.group = goal_privilege_opt_in_entry_point_group(REQUIREMENT.api_major)
        self.goal_file = Path(__file__).resolve()

    def entry(
        self,
        *,
        goal_id: str = REQUIREMENT.goal_id,
        target: str = f"{__name__}:PrivilegeGoal",
        owned_paths: tuple[Path, ...] | None = None,
    ) -> EntryPoint:
        distribution = _Distribution(
            (self.goal_file,) if owned_paths is None else owned_paths
        )
        return EntryPoint(goal_id, target, self.group)._for(distribution)  # type: ignore[arg-type]

    def make_application(
        self,
        goal: PrivilegeGoal,
        entries: tuple[EntryPoint, ...],
        *,
        discover_installed: bool = False,
    ) -> Application[None]:
        def discover(groups, prefixes=()):
            return EntryPointIndex(
                {group: entries if group == self.group else () for group in groups},
                prefixes,
            )

        with (
            patch("engulf.application.is_process_elevated", return_value=True),
            patch(
                "engulf.application.EntryPointIndex.discover",
                side_effect=discover,
            ) as snapshot,
        ):
            application = Application(
                "tests-privilege-application",
                goal,
                display_name="privilege-test",
                vendor="Engulf Tests",
                product="Privilege Tests",
                short_product_name="Privilege",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=discover_installed,
            )
        snapshot.assert_called_once()
        self.assertIn(self.group, snapshot.call_args.args[0])
        return application

    def test_unprivileged_startup_needs_no_metadata_snapshot(self) -> None:
        goal = PrivilegeGoal()
        with (
            patch("engulf.application.is_process_elevated", return_value=False),
            patch("engulf.application.EntryPointIndex.discover") as snapshot,
        ):
            application = Application(
                "tests-privilege-application",
                goal,
                display_name="privilege-test",
                vendor="Engulf Tests",
                product="Privilege Tests",
                short_product_name="Privilege",
                version="0.test",
                discover_installed=False,
            )
        snapshot.assert_not_called()
        self.assertEqual(goal.setup_count, 1)
        application.close()

    def test_exact_owned_declaration_allows_elevated_startup(self) -> None:
        goal = PrivilegeGoal()
        application = self.make_application(goal, (self.entry(),))

        self.assertTrue(application.elevated)
        self.assertEqual(goal.setup_count, 1)
        application.close()

    def test_elevated_startup_denies_missing_wrong_and_unowned_declarations(
        self,
    ) -> None:
        unrelated_file = self.plugin_directory / "unrelated.py"
        unrelated_file.write_text("# unrelated\n", encoding="utf-8")
        cases = (
            ("no installed", ()),
            ("no installed", (self.entry(goal_id="tests.privilege.other"),)),
            (
                "does not target",
                (self.entry(target=f"{__name__}:ChildPrivilegeGoal"),),
            ),
            (
                "does not verifiably own",
                (self.entry(owned_paths=(unrelated_file,)),),
            ),
        )
        for reason, entries in cases:
            with (
                self.subTest(reason=reason),
                self.assertRaisesRegex(GoalPrivilegeError, reason),
            ):
                self.make_application(PrivilegeGoal(), entries)

    def test_parent_declaration_does_not_authorize_subclass(self) -> None:
        with self.assertRaisesRegex(GoalPrivilegeError, "does not target"):
            self.make_application(ChildPrivilegeGoal(), (self.entry(),))

    def test_duplicate_verified_declarations_are_ambiguous(self) -> None:
        with self.assertRaisesRegex(GoalPrivilegeError, "ambiguous"):
            self.make_application(PrivilegeGoal(), (self.entry(), self.entry()))

    def test_missing_file_records_cannot_establish_ownership(self) -> None:
        entry = EntryPoint(
            REQUIREMENT.goal_id,
            f"{__name__}:PrivilegeGoal",
            self.group,
        )._for(_Distribution(None))  # type: ignore[arg-type]
        with self.assertRaisesRegex(GoalPrivilegeError, "does not verifiably own"):
            self.make_application(PrivilegeGoal(), (entry,))

    def test_unreadable_entry_point_snapshot_is_a_privilege_error(self) -> None:
        with (
            patch("engulf.application.is_process_elevated", return_value=True),
            patch(
                "engulf.application.EntryPointIndex.discover",
                side_effect=OSError("metadata unavailable"),
            ),
            self.assertRaisesRegex(
                GoalPrivilegeError,
                "permission metadata is unreadable.*metadata unavailable",
            ),
        ):
            Application(
                "tests-privilege-application",
                PrivilegeGoal(),
                display_name="privilege-test",
                vendor="Engulf Tests",
                product="Privilege Tests",
                short_product_name="Privilege",
                version="0.test",
                discover_installed=False,
            )

    def test_denial_precedes_plugin_directory_resolution_and_loading(self) -> None:
        goal = PrivilegeGoal()
        with (
            patch("engulf.application.is_process_elevated", return_value=True),
            patch(
                "engulf.application.EntryPointIndex.discover",
                return_value=EntryPointIndex({self.group: ()}),
            ),
            patch("engulf.application.resolve_plugin_directory") as resolve_directory,
            patch("engulf.application.load_directory_plugins") as load_plugins,
            self.assertRaises(GoalPrivilegeError),
        ):
            Application(
                "tests-privilege-application",
                goal,
                display_name="privilege-test",
                vendor="Engulf Tests",
                product="Privilege Tests",
                short_product_name="Privilege",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )
        resolve_directory.assert_not_called()
        load_plugins.assert_not_called()
        self.assertEqual(goal.setup_count, 0)

    def test_installed_discovery_reuses_the_privilege_snapshot(self) -> None:
        goal = PrivilegeGoal()
        application = self.make_application(
            goal,
            (self.entry(),),
            discover_installed=True,
        )
        self.assertEqual(application.plugins, ())
        application.close()


if __name__ == "__main__":
    unittest.main()
