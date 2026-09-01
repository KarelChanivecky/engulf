from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import EntryPoint
from pathlib import Path

from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalPhase,
    GoalRequirement,
    GoalResult,
    GoalSetupAPI,
    Invocation,
    Plugin,
    PluginOrder,
    RegistrationAPI,
)

from engulf import (
    goal_plugin_entry_point_group,
    plugin_dependency_entry_point_group,
)

TEST_GOAL_REQUIREMENT = GoalRequirement("tests.engulf.goal", 1)


class CoreTestPlugin(Plugin):
    goal_requirement = TEST_GOAL_REQUIREMENT


def _register_arguments(
    plugin: CoreTestPlugin,
    event: object,
    api: RegistrationAPI,
) -> None:
    del event
    callback = getattr(plugin, "register_arguments", None)
    if callback is not None:
        callback(_NullRegistry(), api)


def _register_completions(
    plugin: CoreTestPlugin,
    event: object,
    api: RegistrationAPI,
) -> None:
    del event
    callback = getattr(plugin, "register_completions", None)
    if callback is not None:
        callback(_NullRegistry(), api)


def _collect_help(
    plugin: CoreTestPlugin,
    event: object,
    api: RegistrationAPI,
) -> None:
    del event
    callback = getattr(plugin, "help", None)
    if callback is not None:
        callback(api)


_REGISTER_ARGUMENTS = GoalPhase(
    phase_id="tests.engulf.setup.arguments",
    order=PluginOrder.PREPROCESS,
    local_callback=_register_arguments,
)
_REGISTER_COMPLETIONS = GoalPhase(
    phase_id="tests.engulf.setup.completions",
    order=PluginOrder.PREPROCESS,
    local_callback=_register_completions,
)
_COLLECT_HELP = GoalPhase(
    phase_id="tests.engulf.setup.help",
    order=PluginOrder.PREPROCESS,
    local_callback=_collect_help,
)


class _NullRegistry:
    def option(self, *args, **kwargs) -> None:
        del args, kwargs

    def candidate(self, *args, **kwargs) -> None:
        del args, kwargs

    def provider(self, *args, **kwargs) -> None:
        del args, kwargs


class PassGoal(Goal[tuple[str, ...]]):
    _contract = GoalContract(TEST_GOAL_REQUIREMENT, CoreTestPlugin)

    def __init__(self, *, exit_code: int = 0) -> None:
        self.exit_code = exit_code

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def setup(self, api: GoalSetupAPI) -> None:
        api.dispatch(_REGISTER_ARGUMENTS, None)
        api.dispatch(_REGISTER_COMPLETIONS, None)
        api.dispatch(_COLLECT_HELP, None)

    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[tuple[str, ...]]:
        del api
        return GoalResult.completed(invocation.arguments, exit_code=self.exit_code)


def empty_plugin_directory(root: Path) -> Path:
    directory = root / "plugins"
    directory.mkdir(exist_ok=True)
    return directory


ORDERING_FIXTURE_MODULE = "engulf_ordering_fixture"
ORDERING_FIXTURE = """
from support import CoreTestPlugin

calls: list[str] = []


class OrderedPlugin(CoreTestPlugin):
    def __init__(self, plugin_id: str, priority: int = 50) -> None:
        self.plugin_id = plugin_id
        self.priority = priority

    def before_goal(self, invocation, api):
        del invocation, api
        calls.append(f"{self.plugin_id}.before")
        return None

    def after_goal(self, invocation, result, api):
        del invocation, api
        calls.append(f"{self.plugin_id}.after")
        return result


high = OrderedPlugin("tests.order.high", 100)
mid = OrderedPlugin("tests.order.mid", 50)
other = OrderedPlugin("tests.order.other", 50)
low = OrderedPlugin("tests.order.low", 0)
"""

ORDERING_PLUGIN_IDS = {
    "high": "tests.order.high",
    "mid": "tests.order.mid",
    "other": "tests.order.other",
    "low": "tests.order.low",
}


def write_ordering_fixture(directory: Path) -> None:
    """Write the importable module backing installed ordering fixtures."""
    (directory / f"{ORDERING_FIXTURE_MODULE}.py").write_text(
        ORDERING_FIXTURE,
        encoding="utf-8",
    )


def ordering_catalog_entry(export: str) -> EntryPoint:
    """Return the goal catalog entry point for one fixture plugin."""
    return EntryPoint(
        ORDERING_PLUGIN_IDS[export],
        f"{ORDERING_FIXTURE_MODULE}:{export}",
        goal_plugin_entry_point_group(
            TEST_GOAL_REQUIREMENT.goal_id,
            TEST_GOAL_REQUIREMENT.api_major,
        ),
    )


def ordering_dependency_entries(
    export: str,
    dependencies: dict[str, str],
) -> tuple[EntryPoint, ...]:
    """Return one fixture plugin's declared dependency entry points."""
    group = plugin_dependency_entry_point_group(ORDERING_PLUGIN_IDS[export])
    return tuple(
        EntryPoint(dependency_id, ordering, group)
        for dependency_id, ordering in dependencies.items()
    )


def ordering_entry_points(
    exports: Iterable[str],
    dependencies: dict[str, dict[str, str]] | None = None,
) -> tuple[EntryPoint, ...]:
    """Return the catalog and dependency entry points for one fixture set."""
    declared = dependencies or {}
    entries: list[EntryPoint] = [ordering_catalog_entry(export) for export in exports]
    for export, mapping in declared.items():
        entries.extend(ordering_dependency_entries(export, mapping))
    return tuple(entries)
