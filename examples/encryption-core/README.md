# Encryption Example Core

This script-free distribution owns the reusable `EncryptionGoal`, its plugin
contract, and `ENCRYPTION_APPLICATION`. Official and vendor launcher wheels depend
on this package and create a fresh managed application from that definition.

It demonstrates a goal whose outcome is implemented entirely in Python—Engulf is
not limited to wrapping executables. The package intentionally defines no console
script, so installing a vendor edition does not also install the official command.

## Source Layout And Public Objects

`engulf_encryption_example_core.goal` defines:

- `ENCRYPTION_REQUIREMENT`, goal ID `org.engulf.example.encryption` at API major 1;
- `EncryptionPlugin`, the only plugin adapter type accepted by this goal;
- `EncryptionGoal`, a `Goal[Path]` whose successful value is the output path.

The package top level additionally exports `ENCRYPTION_APPLICATION`, a side-effect-free
`ApplicationDefinition`. Its declared `org.engulf.example.encryption` identity is
normalized to application ID `org-engulf-example-encryption`; its display name is
`engulf-encrypt`, and its factory creates a fresh `EncryptionGoal`. Importing any of
these objects performs no discovery or setup.

The example follows the reusable-goal pattern:

1. Define one module-level `GoalRequirement` and one goal-specific `Plugin` base.
2. Bind them with `GoalContract` and expose it through `Goal.contract`.
3. Read command-facing branding from `GoalSetupAPI.display_name` during one-time
   setup instead of hard-coding the launcher name.
4. Parse only goal-owned modes inside `achieve()`; subcommands do not become separate
   Engulf goals.
5. Return `GoalResult.rejected(2)` for invalid command input,
   `GoalResult.failed(1)` for file/key/cryptography failures, and
   `GoalResult.completed(output_path)` after success.

`generate-key` writes a Fernet key and requests owner-only mode 0600. `encrypt` and
`decrypt` read the selected key and input file, then replace the requested output
file. These are domain output files chosen by the caller, not Engulf-managed plugin
state. Parent directories must already exist, and callers should protect keys and
plaintext according to their environment; this package is an architecture example,
not a key-management system.

## Reusing The Definition

The official launcher imports the definition and calls `create()`. A differently
branded launcher for the same logical application should derive an additive
`edition()`, preserving application declarations, state, and leases. An independent
product should use `fork()` with a new application ID.

Plugins written specifically for this example derive from `EncryptionPlugin` and
publish their adapter in:

```text
engulf.plugins.v1.goal.v1.org_engulf_example_encryption
```

Plugin-side consent for the shared application uses:

```text
engulf.plugins.v1.application.org_engulf_example_encryption
```

The default application policy is declared mode. A vendor-only adapter can omit the
shared application declaration and be selected explicitly by the vendor edition,
preventing the official launcher from activating it merely because it is installed.

This compact example co-locates the goal contract and application definition, so its
core distribution depends on the `engulf` runtime. A production goal intended as a
third-party plugin ecosystem should split the `GoalRequirement`, event/contribution
models, and plugin base into a dependency-light goal API wheel. Plugin wheels then
depend on `engulf-api` and that goal API wheel, not on the runtime implementation.

See the [thin application package](../encryption-app/README.md) for commands and a
complete edition launcher.
