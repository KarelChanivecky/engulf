# Privilege opt-in for goals

Status: implemented.

## Summary

Reject elevated application startup unless the goal explicitly opts in through
installed package metadata. Apply this to existing POSIX root and Windows
administrator detection.

Keep all existing goals, including `ExecutableWrapperGoal`, opted out.
Unprivileged execution continues without requiring a declaration.

## Metadata contract

Declare permission in the goal implementation's `pyproject.toml`:

```toml
[project.entry-points."engulf.privilege_opt_in.v1.goal.v1"]
"com.example.report" = "example_report.goal:ReportGoal"
```

- The first `v1` versions the declaration format; the second identifies the
  goal API major. The entry-point name must equal the goal ID.
- The target must name the concrete goal class using its defining module and
  qualified class name. Parent-class declarations do not authorize subclasses.
- Read metadata without loading the entry point. Standard entry-point metadata
  is included in installed distributions.
- Verify ownership by matching the loaded goal module's canonical file path
  against files recorded by the declaring distribution. Accept exactly one
  matching declaration with verified ownership.
- Missing, malformed, unreadable, ambiguous, or unverifiable declarations deny
  elevated startup. Other packages' declarations cannot grant permission
  without matching target and file ownership.
- Keep `GoalContract` unchanged. Do not infer ownership from package names or
  fall back to a working-directory `pyproject.toml`. Editable installs require
  sufficient installed file records; otherwise elevated startup is denied.

## Runtime changes

- Move elevation detection into early `Application` construction, after basic
  application and goal-contract validation.
- Perform the gate before resolving or loading directory plugins, loading
  installed plugin targets, creating execution endpoints, starting diagnostics,
  or running goal setup.
- Extend the existing application-scoped entry-point snapshot with the privilege
  group. Reuse that snapshot and its distribution-identity cache for subsequent
  discovery; introduce no process-global cache.
- Enforce the gate with `discover_installed=False` as well. That flag continues
  to disable installed plugin discovery, while elevated startup still reads
  permission metadata.
- Enforce the gate with a dedicated `GoalPrivilegeError(RuntimeError)` exported
  from `engulf`. Include the application name, goal identity, and rejection
  reason.
- Update the example launcher and documented launcher patterns to report this
  error on stderr and return framework exit 70.
- Preserve existing plugin elevation requirements after authorization, using
  the elevation value detected during construction.
- Provide no command-line, environment, application-policy, help, or diagnostic
  exception to the gate.

The boundary begins at `Application` construction: application imports and goal
construction have already occurred. This feature records startup consent; it does
not establish package trust or prevent later programmatic elevation.

## Validation and documentation

- Verify default denial and successful opt-in under simulated POSIX and Windows
  elevation; test unchanged unprivileged startup.
- Assert denied construction performs no plugin imports, factories, endpoint
  creation, registration, goal setup, or diagnostic execution.
- Cover incorrect goal ID, API major, target, unrelated distributions, duplicate
  declarations, missing file records, subclasses, and both installed-discovery
  settings.
- Exercise metadata from a built wheel and an editable installation; verify
  denial when editable ownership cannot be established.
- Preserve one entry-point snapshot per application and fresh discovery for each
  new application.
- Make ordinary application tests independent of the runner's privileges;
  explicitly provide authorization fixtures for elevated-success tests.
- Document the declaration, editable-install limitation, launcher handling, and
  intentional change to existing elevated applications in the owning READMEs.
- Run the workspace-required test, lint, formatting, and typing checks. Run
  `./build.sh` if package metadata changes. Keep existing versions and API majors
  unchanged.
