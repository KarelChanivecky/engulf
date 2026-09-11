from __future__ import annotations

import sys
from pathlib import Path
from typing import Never

from engulf_api import Goal, GoalContract, validate_global_identifier

from .plugin_loader import EntryPointIndex

_PRIVILEGE_OPT_IN_FORMAT_MAJOR = 1


class GoalPrivilegeError(RuntimeError):
    """Raised when an elevated application goal has not opted in."""


def goal_privilege_opt_in_entry_point_group(goal_api_major: int) -> str:
    """Return the installed-metadata group for one goal API major."""
    if type(goal_api_major) is not int or goal_api_major < 1:
        raise ValueError("goal API major must be a positive integer")
    return (
        f"engulf.privilege_opt_in.v{_PRIVILEGE_OPT_IN_FORMAT_MAJOR}."
        f"goal.v{goal_api_major}"
    )


def validate_goal_privilege(
    goal: Goal[object],
    contract: GoalContract,
    *,
    application_name: str,
    entry_point_index: EntryPointIndex,
) -> None:
    """Require an owned, exact installed opt-in for an elevated goal."""
    if not isinstance(goal, Goal):
        raise TypeError("goal must be a Goal")
    if not isinstance(contract, GoalContract):
        raise TypeError("contract must be a GoalContract")
    if not isinstance(application_name, str) or not application_name:
        raise ValueError("application_name must be a nonempty string")
    if not isinstance(entry_point_index, EntryPointIndex):
        raise TypeError("entry_point_index must be an EntryPointIndex")

    goal_id = validate_global_identifier(contract.goal_id, label="goal_id")
    group = goal_privilege_opt_in_entry_point_group(contract.api_major)
    implementation = type(goal)
    target = f"{implementation.__module__}:{implementation.__qualname__}"
    module = sys.modules.get(implementation.__module__)
    module_file = None if module is None else getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        _deny(application_name, contract, "the concrete goal module has no file")
    try:
        goal_path = Path(module_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _deny(
            application_name,
            contract,
            f"the concrete goal module file is unreadable ({error})",
        )

    try:
        named = tuple(
            entry_point
            for entry_point in entry_point_index.entries(group)
            if entry_point.name == goal_id
        )
    except Exception as error:  # noqa: BLE001 - installed metadata is untrusted.
        _deny(
            application_name, contract, f"permission metadata is unreadable ({error})"
        )
    if not named:
        _deny(application_name, contract, "no installed privilege opt-in was declared")

    matching = tuple(
        entry_point for entry_point in named if entry_point.value == target
    )
    if not matching:
        _deny(
            application_name,
            contract,
            f"the installed declaration does not target {target!r}",
        )

    verified = tuple(
        entry_point
        for entry_point in matching
        if entry_point_index.distribution_owns_path(entry_point, goal_path)
    )
    if not verified:
        _deny(
            application_name,
            contract,
            "the declaring distribution does not verifiably own the concrete "
            f"goal module {str(goal_path)!r}",
        )
    if len(verified) != 1:
        _deny(
            application_name,
            contract,
            f"{len(verified)} verified privilege declarations are ambiguous",
        )


def _deny(application_name: str, contract: GoalContract, reason: str) -> Never:
    identity = f"{contract.goal_id!r} API major {contract.api_major}"
    raise GoalPrivilegeError(
        f"application {application_name!r} cannot start elevated with goal "
        f"{identity}: {reason}"
    )


__all__ = [
    "GoalPrivilegeError",
    "goal_privilege_opt_in_entry_point_group",
]
