# Execution platform strategy

Back to [executable support](../README.md). The wrapper delegates OS mechanisms to
an internal `ExecutionPlatformStrategy`. The wrapper remains the lifecycle and
process owner; delegating the OS calls does not give the helper permission to spawn,
signal or reap the child.

| Strategy | B behavior |
| --- | --- |
| `LinuxExecutionStrategy` | Preserve current executable resolution, shell-free spawn, controlling terminal/process group, signals, polling, waiting and reaping; support native launch/readiness bindings |
| `WindowsExecutionStrategy` | Explicitly unavailable stub; support probe is side-effect free, execution/binding/wait operations raise `ExecutionSupportUnavailableError` |
| Unknown platform | Explicitly unsupported strategy; no implicit Linux selection |

Select the execution strategy once at wrapper composition, using a fixed local
platform mapping and deferred concrete imports. Keep OS branches out of lifecycle
traversal, portable helpers and core. Do not broaden the existing wrapper's platform
support as a side effect of this refactoring. When support is unused, preserve its
current execution behavior and exceptions.

The current [goal module](../../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L57)
builds a module-level tuple of POSIX signal constants, and the package initializer
imports that module. B2 must move this evaluation and its OS-specific collaborators
into the Linux strategy; otherwise Windows can fail during import before reaching
its stub. Make the facade and stub importable first, then reject unsupported
execution explicitly before goal work. This is import portability, not a Windows
wrapper implementation.

## Generic contract and private native bindings

The [A definitions](../contracts.md) replace native `pass_fds` and `fd` fields with
opaque `ExecutionLaunchAttachment` and `ExecutionWaitResource` interfaces. These
are local runtime resources, never serializable service values. They do not expose
a universal integer handle or a `fileno()` requirement.

The base launch attachment requires idempotent `close()`; a wait resource identifies
an interest and exposes no native fields. Both belong to one session and have stable
object identity. Concrete strategies validate resource kind, owner, liveness and
supported native binding. A same-looking resource from another session is invalid;
integers and arbitrary dictionaries are not accepted in their place.

In B, define the shared Unix adapter contract in a dedicated wrapper-API platform
module containing only OS-independent type declarations. The optional services
Unix wrapper binding implements it around its owned endpoints; the Linux execution
strategy consumes it. Native fd/identity access is confined to those concrete
adapters. The API module imports neither OS implementations nor services. Portable
code uses only the base interfaces, so a later Windows adapter can supply a
different native subtype without changing the generic records frozen in A.

These are capabilities held by trusted runtime integration code. Nominal types and
ownership validation prevent accidental mixing; they are not an OS security boundary.

## Strategy pseudocode

Names below describe private B behavior; only the public records in the contract
page are frozen by A.

```text
ExecutionPlatformStrategy:
    support -> ExecutionPlatformSupport
    prepare_launch(launch, session_owner) -> OwnedLaunch
    spawn(resolved_call, environment, owned_launch) -> OwnedProcess
    attach_signals(process) -> SignalRestoration
    wait(interests, timeout, session_owner) -> tuple[ExecutionReady, ...]

OwnedProcess:                                 # retained only by the wrapper
    pid -> int
    poll() -> CallOutcome | None
    wait() -> CallOutcome
    terminate_and_reap() -> None

WindowsExecutionStrategy:
    support -> unavailable("executable support is not implemented on Windows",
                           binding_ids=frozenset())
    prepare_launch / spawn / attach_signals / wait -> raise unavailable
```

`prepare_launch` validates the complete attachment tuple before native preparation
and unwinds any partial acquisition. It returns an owned, idempotently closable
launch binding. Native launch options such as `pass_fds` never leave that strategy.
The wrapper snapshots launch data immediately after successful helper `open` and
retains attachment references for exhaustive cleanup even if later validation,
preparation, spawn or notification fails. Shared ownership records make helper and
wrapper backstop closure idempotent; they must not each close a copied raw fd.

Only `spawn`'s existing executable-resolution/OS-launch error mapping produces
127/126. Resource validation, helper code and readiness failures remain support
failures outside that narrow mapping. The strategy returns a process abstraction,
not a `Popen` to the helper. Process waiting, signal restoration and child outcome
normalization stay within the strategy; the lifecycle decides when to request them.

`wait` validates every opaque interest and maps OS events to `ExecutionReady` with
the identical resource object. Results cannot reference a closed, foreign or
unrequested resource. Empty interest sets still honor the bounded timeout and allow
`step(())` to process deadlines. A future completion-based backend may implement
these semantics differently; generic code cannot assume selector-compatible fds.

The Linux strategy retains direct-child SIGTERM, one-second grace, SIGKILL if still
alive and reaping on termination. It preserves the existing designated wait-region
Ctrl-C behavior. The generic loop distinguishes waiting from helper/provider calls
without naming POSIX signals. Every signal/restoration path is still tested with
real Linux child processes and a controlling terminal.

## Strategy compatibility and review

The optional services integration binds its selected transport to the wrapper's
execution strategy through a fixed local adapter. The wrapper passes only an
immutable `ExecutionPlatformSupport` snapshot into `support.open`. The helper
checks availability and its adapter's binding ID against the snapshot before
allocating endpoints or child scopes. Strategy selection belongs to local
composition; wire data, provider metadata and shared context cannot select it.
There is no general plugin-discovered strategy registry or new public constructor
argument in A.

Use a fake strategy with resource objects lacking `fileno`, integer handles and
native fields to exercise the generic launch/interest/ready loop. Test incompatible
bindings, closed/foreign resources, partial prepare failures, duplicate close,
notification failure and no-op disabled support. Keep native Linux process tests
for actual inheritance/signals/reaping and native Windows tests for the importable
unavailable strategy, including import through the normal package initializer.
This is W-STRATEGY, in addition to W-LIFE and W-PROC.
