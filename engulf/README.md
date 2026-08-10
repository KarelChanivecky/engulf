# engulf

`engulf` is the managed runtime for goal-oriented, plugin-based CLI applications.
It depends on `engulf-api` and implements application lifecycle, installed-plugin
discovery, dependency ordering, diagnostics, persistent state, transactions,
resource leases, and workspace cleanup.

The runtime supports POSIX and Windows. Goals and plugins may impose narrower
platform requirements, but discovery, lifecycle, diagnostics, context, and managed
state do not require the executable-wrapper runtime.

It does not contain executable-wrapper events, argument edits, process execution,
help aggregation, or shell completion. Those live in the executable-wrapper goal
packages.

## Constructing An Application

```python
from engulf import Application, PluginPolicy
from my_report_goal import ReportGoal

application = Application(
    application_id="com.example.report-cli",
    goal=ReportGoal(),
    display_name="report-cli",
    plugin_policy=PluginPolicy.declared(
        include={"com.example.shared.audit"},
    ),
)


def main() -> int:
    return application.run()
```

`application_id` is normalized to lowercase distribution form. Keep it stable: it
participates in plugin discovery, state paths, and named lease identity.

The `Goal` instance belongs to one application. `Goal.setup()` runs once after
plugin discovery. Every `invoke()` creates a fresh `Invocation`, context table,
state manager, diagnostics session, and lifecycle capability set.

## Invocation Lifecycle

One invocation follows this order:

1. Validate arguments and resolve per-invocation logging controls.
2. Create immutable invocation, context, state, and diagnostics facilities.
3. Run universal `before_goal` hooks in preprocessing order.
4. Stop at the first returned `GoalResult`, or call `Goal.achieve()`.
5. Let the goal dispatch any typed inner phases it defines.
6. Run `after_goal` middleware in postprocessing order for entered plugins.
7. Release capabilities, finalize requested workspace destruction, and report unused
   context writes.

Callback exceptions become `FRAMEWORK_FAILED` results with exit code 70. Goal phase
exceptions identify the stable `plugin_id`, not a Python class name.

Use `application.invoke(args)` when the typed `GoalResult` matters. Use
`application.run(args)` for a console entry point.

## Installed Plugin Catalogs

Installed discovery reads entry-point metadata before importing plugin modules. A
plugin package can publish two kinds of declaration.

### Goal Catalog

Every installed plugin adapter must be registered in its exact goal catalog:

```text
engulf.plugins.v<PLUGIN_API_MAJOR>.goal.v<GOAL_API_MAJOR>.<normalized_goal_id>
```

For goal `org.engulf.executable-wrapper` API major 1, the group is:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
```

The entry-point name must be the exact stable `plugin_id`:

```toml
[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"com.example.audit" = "example_audit:plugin"
```

The group selects goal ID and major before import. After import, Engulf also checks
the plugin's `GoalRequirement`, required runtime plugin type, and exported
`plugin_id`.

### Plugin-Side Application Declaration

A plugin opts into one application by repeating the same ID and target in the
application group:

```toml
[project.entry-points."engulf.plugins.v1.application.com_example_cli"]
"com.example.audit" = "example_audit:plugin"
```

To support multiple applications, add one application-group entry for each. The
goal-catalog implementation remains single and reusable. An application declaration
must come from the same distribution, version, and import target as the matching
goal-catalog entry.

Use the exported helpers to compute exact groups:

```python
from engulf import (
    application_plugin_entry_point_group,
    goal_plugin_entry_point_group,
)

print(application_plugin_entry_point_group("com.example.cli"))
print(goal_plugin_entry_point_group("org.engulf.executable-wrapper", 1))
```

## Application-Side Activation Policies

Technical goal compatibility is always mandatory. Within that compatible catalog,
the application selects one policy:

```python
# Either the plugin names this app or the app includes the ID.
PluginPolicy.declared(include={"com.example.audit"})

# Ignore plugin-side app declarations; activate only these named IDs.
PluginPolicy.allow_only({"com.example.audit"})

# Also activate their transitive PluginDependency targets.
PluginPolicy.allow_only(
    {"com.example.audit"},
    include_dependencies=True,
)

# Activate every goal-compatible installed plugin except these IDs.
PluginPolicy.allow_all_except({"com.example.unsafe"})
```

Explicit IDs are optional: an ID absent from the current goal catalog is skipped and
listed by `application.missing_policy_ids`. This supports optional installations.
By default, every dependency of an allowlisted plugin must also be explicitly
allowlisted. Set `include_dependencies=True` to activate reachable
`PluginDependency` targets recursively from the same goal catalog or plugin
directory. Dependencies that are unavailable still fail application construction.
Implicit dependencies do not need plugin-side application declarations because the
application's allowlist selected them, but exact goal ID, goal API major, and runtime
plugin type checks still apply.
The option is valid only for `allow_only()`; declared and blocklist policies already
define their complete candidate sets.

Catalog IDs are validated and deduplicated before any selected target is imported.
An unselected goal-catalog entry is not imported. Blocklist mode deliberately
selects and imports every compatible catalog entry not blocked.

## Local Plugin Directory

`plugin_dir` supports application-owned development plugins. Every immediate,
non-private `*.py` file must export `plugin` as an instance or zero-argument factory.
Private helper modules remain importable. Files load in lexical order.

Supplying a directory is itself an application-side declaration, so declared mode
activates all technically compatible directory plugins. Allowlist and blocklist
filter directory plugins by their exported IDs after import. Directory code cannot
be filtered before import because it has no installed metadata catalog.

## Dependencies And Ordering

Engulf resolves two deterministic topological orders:

- preprocessing for outer before hooks and goal phases that choose `PREPROCESS`;
- postprocessing for outer after hooks and goal phases that choose `POSTPROCESS`.

`PluginDependency` expresses presence and independent edges for both orders.
Priority defaults to 50 and breaks ties only among currently ready nodes. Higher
priority runs first. Duplicate IDs, missing dependencies, self-dependencies, repeated
dependency declarations, and cycles are startup errors.

Package dependencies in a plugin wheel make another wheel available; they do not
activate its plugin entry point. Both adapters must still be selected by application
policy, either explicitly or through `allow_only(..., include_dependencies=True)`.
Implicit activation follows Engulf `PluginDependency` metadata, not Python package
dependency metadata.

## Elevation

Plugins declare one `ElevationRequirement`: `NONE`, `OPTIONAL`, or `REQUIRED`.
Required elevation is validated after discovery and ordering but before goal setup
or any plugin registration callback. A selected required plugin in an unprivileged
process raises `PluginElevationError`; Engulf does not elevate or restart itself.

Optional plugins remain active without elevation and can degrade deliberately:

```python
from engulf_api import ElevationRequirement


class NetworkPlugin(MyGoalPlugin):
    elevation_requirement = ElevationRequirement.OPTIONAL

    def before_goal(self, invocation, api):
        if api.elevated:
            configure_system_networking()
```

`api.elevated` is available during registration and invocation callbacks and is
callback-bound like the other capabilities. `Application.elevated` exposes the same
process snapshot to application code. On POSIX elevation means effective UID zero;
on Windows it means an elevated process token.

## Logging

Each registration and invocation callback receives `api.logger`, already configured
for that plugin. The logger intentionally omits handler and level mutation methods.
It is valid only during the active callback.

```python
def before_goal(self, invocation, api):
    api.logger.debug("checking %d arguments", len(invocation.arguments))
```

Applications configure defaults with `LoggingConfig` and can override levels per
invocation with `LogLevelOverrides`. Every application reserves:

```text
--<display-name>-log-level LEVEL
--<display-name>-plugin-log-level PLUGIN_ID=LEVEL
```

Controls before `--` are removed from the goal's arguments. Controls after `--` are
left untouched. Registration logging uses the initialized setup diagnostics session;
catalog candidates that are never activated are never imported and therefore cannot
log.

## State And Workspaces

Plugins and the goal receive sandboxed user and workspace stores:

```python
from engulf_api import StateScope

user = api.state(StateScope.USER)
workspace = api.state(StateScope.WORKSPACE)
user.write_text("settings.json", data)
workspace.write_bytes("artifact", payload)
```

One filename is one path component. Reads reject symbolic links and Windows reparse
points. Writes are atomic, private, and owner-aware. Calling `directory` or `path()`
exposes the sandboxed directory so plugins can clone repositories or manage
directory trees inside their own namespace. `delete()` removes a named file or tree.
`WorkspaceState.destroy()` queues namespace destruction after postprocessing; an
empty workspace record is pruned.

On POSIX, the default state home follows `XDG_STATE_HOME` or `~/.local/state`. Under
a valid sudo invocation, state uses the invoking non-root user's home and ownership.
On Windows, it uses `%LOCALAPPDATA%\Engulf\State`, the process-token user SID,
protected owner/SYSTEM/Administrators DACLs, and non-inheritable `LockFileEx`
handles. POSIX uses private modes, ownership, no-follow opens, and `flock`.

`StateHomeResolver` and `WorkspaceRootResolver` are application policy and receive
stable context records. `StateHomeContext` exposes `application_id`, a
platform-qualified `owner_id`, `owner_home`, and whether the process is elevated;
it does not expose platform-specific UID/GID or sudo fields.

## Transactions And Leases

Atomic file replacement does not serialize read-modify-write sequences:

```python
with user.transaction(timeout=5) as locked:
    value = int(locked.read_text("counter"))
    locked.write_text("counter", str(value + 1))
```

Transactions serialize; they do not roll back. Ordinary reads take shared store
locks, writes take exclusive locks, and workspace destruction waits for the affected
store lock.

Named leases coordinate external resources across cooperating Engulf processes that
share state owner/home and application ID:

```python
with api.leases((f"docker-image:{image}", f"builder:{builder.resolve()}")):
    build_image()
    with user.transaction() as locked:
        save_fingerprint(locked)
```

Lease identity excludes plugin ID, so different plugins contend on the same exact
name. Acquire leases before state transactions. Acquiring a lease from inside a
transaction is rejected; nested leases and transactions are also rejected. Lock
files persist to avoid file-replacement races and use non-inheritable advisory-lock
handles.

Leases coordinate only cooperating Engulf processes. External resources still need
ownership markers and recovery journals.
