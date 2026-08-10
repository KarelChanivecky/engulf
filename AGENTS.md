# Agent Guide

This file applies to the whole workspace. Read the README owned by the subsystem
before editing it. Do not infer contracts from the removed `Engulf`, `BinaryWrapper`,
`before_call`, or edit-capability APIs.

## Package Boundaries

| Distribution | Import | Owns |
| --- | --- | --- |
| `engulf-api` | `engulf_api` | Stable goal, plugin, lifecycle, logging, and state interfaces |
| `engulf` | `engulf` | `Application`, discovery, ordering, diagnostics, state, locks, and dispatch |
| `engulf-executable-wrapper-api` | `engulf_executable_wrapper_api` | Wrapper events, contributions, registries, and plugin adapter |
| `engulf-executable-wrapper` | `engulf_executable_wrapper` | Executable goal, process runner, help, and completion |

Dependency direction is one-way:

```text
engulf-api <- engulf <- engulf-executable-wrapper
     ^                       ^
     `-- engulf-executable-wrapper-api --'
```

- `engulf-api` remains dependency-free and never imports a runtime package.
- Generic framework code must not import executable-wrapper packages.
- `engulf-api`, `engulf`, and goal API packages remain OS-independent. Keep POSIX
  imports in `engulf._state_posix` and Windows API use in `engulf._state_windows`.
- `engulf-executable-wrapper` is intentionally Linux-specific; do not let its signal,
  process-group, or shell-completion assumptions leak into core.
- Goal plugin wheels depend on `engulf-api` and their goal-specific API package, not
  the runtime implementation.
- Every public package is typed and includes `py.typed`.

Do not bump existing versions while the first release is under development.
`PLUGIN_API_MAJOR` remains 1. New goal API packages independently declare their goal
major.

## Developing An Application

Every application owns exactly one goal:

```python
from engulf import Application, PluginPolicy

application = Application(
    application_id="com.example.app",
    goal=MyGoal(),
    display_name="example-app",
    plugin_policy=PluginPolicy.declared(),
)
```

Treat `application_id` as persistent compatibility and state metadata. Changing it
changes application entry-point discovery, state location, and lease identity.
`display_name` controls diagnostics and reserved logging option names.

Select installed plugins deliberately:

- `PluginPolicy.declared(include=...)`: union plugin-side app declarations with IDs
  drawn in by the application.
- `PluginPolicy.allow_only(...)`: ignore plugin-side declarations and activate only
  named IDs. Dependencies must also be named unless `include_dependencies=True`,
  which recursively activates reachable `PluginDependency` targets.
- `PluginPolicy.allow_all_except(...)`: activate every current-goal catalog entry
  except blocked IDs.

Explicit IDs are optional when absent. Dependencies reached from an active plugin
are never optional, including when implicit dependency activation is enabled.
Do not use application policy to bypass goal ID, goal API major, or plugin runtime
type checks.

Use `plugin_dir` only for application-owned or development plugins. Installed wheels
must use entry points.

## Developing A Goal

A goal defines an invocation's outcome and process. Implement:

- stable `GoalContract(GoalRequirement(goal_id, api_major), plugin_type)`;
- optional one-time `setup(GoalSetupAPI)`;
- per-invocation `achieve(Invocation, GoalAPI) -> GoalResult[T]`.

Goal commands or modes remain internal to one goal. Do not create a separate goal per
subcommand unless the application truly has different invocation outcomes.

Dispatch goal-specific plugin callbacks through immutable `GoalPhase` values. Every
phase selects one shared `PluginOrder`: preprocessing or postprocessing. Return
immutable contributions and let the goal merge them only after dispatch completes.
Plugins must not observe other plugins' contributions during their callback.

The goal receives managed diagnostics, context, state, transactions, leases, and
workspaces under a reserved goal namespace. Do not bypass these facilities with
ad-hoc global storage or lock files.

Goal exceptions and invalid phase returns become framework failures. Preserve stable
plugin IDs in diagnostics and attributed results.

## Developing A Plugin

Every adapter derives from the goal's plugin type and declares one globally unique,
lowercase, dot-qualified `plugin_id`. Base priority is 50. Declare privilege use with
`ElevationRequirement.NONE`, `OPTIONAL`, or `REQUIRED`; never probe or elevate at
module import time. Required elevation fails application construction before setup,
while optional plugins must branch on callback-bound `api.elevated` and provide a
coherent unprivileged path.

Installed metadata requires a goal catalog entry whose name equals `plugin_id`:

```toml
[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"com.example.plugin" = "example_plugin:plugin"
```

Plugin-side consent for an application repeats the same ID and target:

```toml
[project.entry-points."engulf.plugins.v1.application.com_example_app"]
"com.example.plugin" = "example_plugin:plugin"
```

Repeat the application table for every application supported by one implementation.
An application may activate the goal-catalog entry without this second declaration.
A package spanning unrelated goals exports separate adapters under each goal catalog;
do not add wildcard goal compatibility.

Wheel dependencies make code installable. `PluginDependency` separately requires an
adapter to be active and defines independent preprocess/postprocess ordering. Neither
mechanism replaces the other.

Use callback `api.logger`; do not attach handlers or change logger levels. Registration
logging is available after activation because unselected catalog modules are never
imported. Retained loggers and APIs must fail outside their callback.

## Executable-Wrapper Plugins

Derive from `ExecutableWrapperPlugin` and keep phases distinct:

- `analyze_call`: side-effect free; return immutable removals, additions, and optional
  preemption after inspecting original arguments.
- `prepare_call`: perform viable external work only after all vetoes resolve.
- `after_call`: finalize in postprocessing order using the complete outcome.

All analyzers see the same original call. Added arguments are hidden until merge.
Preemption never prevents another analyzer from running, but it prevents every
preparer from running. Use `preempted_by` as a stable plugin ID.

Keep process execution shell-free, inherit standard streams, preserve controlling
terminal behavior, and keep the direct child in the wrapper's process group. Forward
temporary wrapper-PID signals to the child and restore inherited handlers before
postprocessing. Preserve exits 127, 126, `128 + signal`, and framework 70.

Completion and help belong to the executable-wrapper goal packages, not core.
Argument registration is completion metadata only; runtime edits come from returned
`CallContribution` values.

## Context, State, And Locks

Context lives for one `Application.invoke()` and is shared across entered lifecycle
hooks and goal phases. Declare exact `context_reads` and `context_writes`. Context
metadata does not imply dependency ordering.

Use workspace state for deploy/destroy data tied to a canonical workspace. Use user
state for application-global plugin data and `known_workspaces()` for global cleanup
operations such as destroy-all.

State invariants:

- filename APIs accept one path component and preserve link/reparse, owner-private,
  and atomic-write protections;
- `directory` is the sandboxed filesystem view for trees such as cloned repositories;
- reads use shared store locks; directory/path/write/delete operations use exclusive
  locks;
- atomic writes do not make read-modify-write atomic;
- transactions serialize and do not roll back completed writes;
- workspace destruction is deferred, takes the store lock, and prunes empty records;
- queued cleanup is attempted for every participant even after failures.

Lease invariants:

- acquire all external-resource leases before state transactions;
- lease identity includes state owner/home, application ID, and exact name, but not
  plugin ID;
- multi-lease acquisition validates first, deduplicates, sorts, uses one deadline,
  releases partial acquisition on failure, and releases in reverse order;
- lock files remain persistent and non-inheritable; POSIX uses mode 0600 and
  no-follow, while Windows uses protected DACLs and open-reparse-point checks;
- callback deactivation and API close forcibly release leaked lock contexts.

Leases coordinate cooperating Engulf processes only. Keep ownership markers and
recovery journals for bridges, processes, images, firewall rules, and other external
resources.

## Contributing

Keep edits in the owning package. Generic lifecycle changes require contract tests in
`engulf-api` and runtime tests in `engulf`. Wrapper behavior requires corresponding
API/runtime tests in its two packages.

Keep `Application` responsible for discovery, diagnostics sessions, invocation
resources, goal execution, and cleanup. Hook traversal and goal-phase dispatch belong
in `engulf._dispatch`. Keep `RuntimePluginAPI` as the public runtime facade;
activation, context access, state handles, and lock coordination belong to the
collaborators in `engulf._capabilities`.

Before completion, run:

```console
python3.14 -m venv --upgrade-deps .venv
.venv/bin/python -m pip install --group dev
PYTHONPATH=engulf-api/src .venv/bin/python -m unittest discover -s engulf-api/tests -v
PYTHONPATH=engulf-api/src:engulf-executable-wrapper-api/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper-api/tests -v
PYTHONPATH=engulf-api/src:engulf/src .venv/bin/python -m unittest discover -s engulf/tests -v
PYTHONPATH=engulf-api/src:engulf/src:engulf-executable-wrapper-api/src:engulf-executable-wrapper/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper/tests -v
.venv/bin/python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper examples
.venv/bin/python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper examples
.venv/bin/python -m mypy
```

When package metadata changes, build all four wheels and source distributions and run
Twine checks. Do not hand-edit generated archives or publish unless explicitly asked.

Use deterministic subprocess/multiprocessing coordination for lock and signal tests.
Cover failure, ordering, repeated invocation, policy filtering, and non-import of
unselected plugins, not only successful paths.
