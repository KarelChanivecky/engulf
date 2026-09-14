from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from engulf_api import GoalRequirement, InvocationAPI, RegistrationAPI
from engulf_executable_wrapper_api import (
    EXECUTABLE_WRAPPER_API_MAJOR,
    EXECUTABLE_WRAPPER_API_VERSION,
    EXECUTABLE_WRAPPER_GOAL_ID,
    AdditionPlacement,
    ArgumentAddition,
    ArgumentRegistry,
    CallContribution,
    CallMode,
    CompletionCandidate,
    CompletionContext,
    CompletionRegistry,
    ExecutableWrapperPlugin,
    PreparationFailedEvent,
    Shell,
)


class ExamplePlugin(ExecutableWrapperPlugin):
    plugin_id = "tests.wrapper_api.example"


class ExecutableWrapperApiTestCase(unittest.TestCase):
    def test_contract_identity_and_plugin_defaults(self) -> None:
        self.assertEqual(EXECUTABLE_WRAPPER_API_MAJOR, 1)
        self.assertEqual(EXECUTABLE_WRAPPER_API_VERSION, "1.0.0")
        self.assertEqual(EXECUTABLE_WRAPPER_GOAL_ID, "org.engulf.executable-wrapper")
        self.assertEqual(
            ExamplePlugin.goal_requirement,
            GoalRequirement(EXECUTABLE_WRAPPER_GOAL_ID, 1),
        )

    def test_contributions_are_immutable_and_validated(self) -> None:
        addition = ArgumentAddition(
            ("--one", "two"),
            AdditionPlacement.APPEND,
        )
        contribution = CallContribution(
            frozenset({1}),
            (addition,),
            7,
        )
        self.assertEqual(contribution.removals, frozenset({1}))
        self.assertEqual(contribution.preempt_exit_code, 7)
        for invalid in (True, -1, 256):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CallContribution(preempt_exit_code=invalid)
        with self.assertRaises(ValueError):
            ArgumentAddition(())

    def test_preparation_failure_event_is_immutable_and_attributed(self) -> None:
        event = PreparationFailedEvent(
            "example",
            ("--wrapper",),
            ("--wrapper", "--added"),
            CallMode.NORMAL,
            "prepare failed",
            failed_plugin_id="tests.wrapper_api.failing",
            environment={"EXAMPLE": "1"},
        )

        self.assertEqual(event.effective_args, ("--wrapper", "--added"))
        self.assertEqual(event.error, "prepare failed")
        self.assertEqual(event.failed_plugin_id, "tests.wrapper_api.failing")
        self.assertEqual(dict(event.environment), {"EXAMPLE": "1"})
        with self.assertRaises(FrozenInstanceError):
            event.error = "other"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            event.environment["EXAMPLE"] = "2"  # type: ignore[index]

        defaults = PreparationFailedEvent(
            "example",
            (),
            (),
            CallMode.NORMAL,
            "prepare failed",
        )
        self.assertIsNone(defaults.failed_plugin_id)
        self.assertEqual(dict(defaults.environment), {})

        for invalid in ({"error": None}, {"mode": "normal"}, {"failed_plugin_id": "X"}):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises((TypeError, ValueError)),
            ):
                PreparationFailedEvent(
                    "example",
                    (),
                    (),
                    **{
                        "mode": CallMode.NORMAL,
                        "error": "prepare failed",
                        **invalid,
                    },  # type: ignore[arg-type]
                )

    def test_argument_registry_rejects_duplicate_options(self) -> None:
        registry = ArgumentRegistry()
        registry.option("--one")
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.option("--one")

    def test_argument_registry_records_environment_and_predicate(self) -> None:
        registry = ArgumentRegistry()
        predicate = lambda context: context.current.startswith("-")
        option = registry.option(
            "--source",
            takes_value=True,
            environment="EXAMPLE_SOURCE",
            suggest_assignment=False,
            when=predicate,
        )

        self.assertEqual(option.environment, "EXAMPLE_SOURCE")
        self.assertFalse(option.suggest_assignment)
        self.assertIs(option.when, predicate)
        with self.assertRaisesRegex(ValueError, "shell-style"):
            registry.option("--bad", environment="not-valid")

    def test_completion_registry_accepts_candidates_and_providers(self) -> None:
        registry = CompletionRegistry()
        registry.candidate("--static")
        registry.provider(lambda context: [CompletionCandidate("--dynamic")])
        context = CompletionContext(
            Shell.BASH,
            "example",
            "binary",
            ("--",),
            0,
        )
        self.assertEqual(
            [candidate.value for candidate in registry.static_candidates(context)],
            ["--static"],
        )
        self.assertEqual(len(registry.providers), 1)
        self.assertEqual(Shell.FISH.value, "fish")

    def test_plugin_phase_signatures_use_common_managed_apis(self) -> None:
        from typing import get_type_hints

        self.assertIs(
            get_type_hints(ExecutableWrapperPlugin.register_arguments)["api"],
            RegistrationAPI,
        )
        self.assertIs(
            get_type_hints(ExecutableWrapperPlugin.analyze_call)["api"],
            InvocationAPI,
        )
        self.assertIs(
            get_type_hints(ExecutableWrapperPlugin.prepare_failed)["api"],
            InvocationAPI,
        )
        self.assertIs(
            get_type_hints(ExecutableWrapperPlugin.prepare_failed)["event"],
            PreparationFailedEvent,
        )
        self.assertIsNone(
            ExamplePlugin().prepare_failed(
                PreparationFailedEvent(
                    "example",
                    (),
                    (),
                    CallMode.NORMAL,
                    "prepare failed",
                ),
                None,  # type: ignore[arg-type]
            )
        )
        self.assertIs(
            get_type_hints(ExecutableWrapperPlugin.after_call)["api"],
            InvocationAPI,
        )


if __name__ == "__main__":
    unittest.main()
