"""Verify that declared plugin dependencies are also distribution requirements.

Plugin dependencies are declared once, in packaging metadata. Installing the
code they need is still the distribution's job, so every dependency plugin must
come from a distribution this project requires. This check reports the missing
requirement before a wheel ships, instead of leaving it to fail on a user's
machine.

The check resolves each dependency plugin ID through the entry points of the
environment it runs in, so run it where the project's own dependencies are
installed. An isolated wheel build installs only ``build-system.requires`` and
cannot resolve anything.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from .plugin_info import _normalize_distribution_name
from .plugin_loader import (
    PluginLoadError,
    _requirement_name,
    parse_plugin_dependency,
    plugin_dependency_entry_point_prefix,
)

_GOAL_GROUP_PREFIX = "engulf.plugins.v"


@dataclass(frozen=True, slots=True)
class PackagingFinding:
    """One packaging defect or unverifiable declaration in a project."""

    project: str
    plugin_id: str
    dependency_id: str
    message: str

    def __str__(self) -> str:
        return f"{self.project}: {self.message}"


@dataclass(frozen=True, slots=True)
class _Project:
    """The declarations one pyproject.toml makes about plugin dependencies."""

    name: str
    requirements: frozenset[str]
    dependencies: dict[str, tuple[str, ...]]


def check_projects(paths: Iterable[Path]) -> tuple[PackagingFinding, ...]:
    """Return every packaging finding for the given project directories."""
    providers = _installed_plugin_providers()
    findings: list[PackagingFinding] = []
    for path in paths:
        findings.extend(_check_project(_read_project(path), providers))
    return tuple(findings)


def main(argv: Sequence[str] | None = None) -> int:
    """Check one or more project directories and report findings."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or any(argument.startswith("-") for argument in arguments):
        sys.stderr.write(
            "usage: engulf-check-packaging PROJECT_DIRECTORY [PROJECT_DIRECTORY ...]\n"
        )
        return 2
    try:
        findings = check_projects(Path(argument) for argument in arguments)
    except PluginLoadError as error:
        sys.stderr.write(f"error: {error}\n")
        return 2
    for finding in findings:
        sys.stderr.write(f"{finding}\n")
    if findings:
        sys.stderr.write(f"found {len(findings)} plugin packaging problem(s)\n")
        return 1
    return 0


def _read_project(path: Path) -> _Project:
    pyproject = path if path.is_file() else path / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError as error:
        raise PluginLoadError(f"cannot read {pyproject}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise PluginLoadError(f"cannot parse {pyproject}: {error}") from error

    project = data.get("project")
    if not isinstance(project, dict):
        raise PluginLoadError(f"{pyproject} has no [project] table")
    name = project.get("name")
    if not isinstance(name, str) or not name:
        raise PluginLoadError(f"{pyproject} has no project name")

    requirements = {
        _normalize_distribution_name(_requirement_name(requirement))
        for requirement in project.get("dependencies", ())
        if isinstance(requirement, str) and _requirement_name(requirement)
    }
    entry_point_groups = project.get("entry-points")
    dependencies: dict[str, tuple[str, ...]] = {}
    prefix = plugin_dependency_entry_point_prefix()
    if isinstance(entry_point_groups, dict):
        for group, entries in entry_point_groups.items():
            if not group.startswith(prefix) or not isinstance(entries, dict):
                continue
            declaring = group[len(prefix) :]
            declared: list[str] = []
            for dependency_id, ordering in entries.items():
                parse_plugin_dependency(dependency_id, ordering)
                declared.append(dependency_id)
            dependencies[declaring] = tuple(declared)
    return _Project(name, frozenset(requirements), dependencies)


def _check_project(
    project: _Project,
    providers: dict[str, str],
) -> tuple[PackagingFinding, ...]:
    own_name = _normalize_distribution_name(project.name)
    findings: list[PackagingFinding] = []
    for plugin_group, dependency_ids in sorted(project.dependencies.items()):
        for dependency_id in dependency_ids:
            provider = providers.get(dependency_id)
            if provider is None:
                findings.append(
                    PackagingFinding(
                        project.name,
                        plugin_group,
                        dependency_id,
                        f"cannot verify the dependency on {dependency_id!r}: no "
                        "installed distribution provides it; install it in this "
                        "environment, or add it to the project's dependencies",
                    )
                )
                continue
            normalized = _normalize_distribution_name(provider)
            if normalized == own_name or normalized in project.requirements:
                continue
            findings.append(
                PackagingFinding(
                    project.name,
                    plugin_group,
                    dependency_id,
                    f"depends on plugin {dependency_id!r} from distribution "
                    f"{provider!r}, which is missing from the project's "
                    "dependencies",
                )
            )
    return tuple(findings)


def _installed_plugin_providers() -> dict[str, str]:
    """Map every installed plugin ID to the distribution that catalogs it."""
    providers: dict[str, str] = {}
    for entry_point in entry_points():
        if not _is_goal_catalog_group(entry_point.group):
            continue
        name = _distribution_name(entry_point)
        if name is not None:
            providers.setdefault(entry_point.name, name)
    return providers


def _is_goal_catalog_group(group: str) -> bool:
    if not group.startswith(_GOAL_GROUP_PREFIX):
        return False
    remainder = group[len(_GOAL_GROUP_PREFIX) :]
    major, separator, rest = remainder.partition(".")
    return bool(separator) and major.isdigit() and rest.startswith("goal.v")


def _distribution_name(entry_point: EntryPoint) -> str | None:
    distribution = entry_point.dist
    return None if distribution is None else distribution.name


if __name__ == "__main__":
    raise SystemExit(main())
