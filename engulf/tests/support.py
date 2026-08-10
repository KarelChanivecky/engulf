from __future__ import annotations

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
    "tests.engulf.setup.arguments",
    PluginOrder.PREPROCESS,
    _register_arguments,
)
_REGISTER_COMPLETIONS = GoalPhase(
    "tests.engulf.setup.completions",
    PluginOrder.PREPROCESS,
    _register_completions,
)
_COLLECT_HELP = GoalPhase(
    "tests.engulf.setup.help",
    PluginOrder.PREPROCESS,
    _collect_help,
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
