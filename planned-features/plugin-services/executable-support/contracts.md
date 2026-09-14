# Execution-support definitions reserved in A

Back to [executable support](README.md). These definitions belong to
`engulf-executable-wrapper-api` and remain typed and importable on every supported
core OS. They describe an explicitly local execution adapter using opaque resources.
The [execution strategy](strategies/README.md) hides native launch/wait/process
behavior; the Windows strategy is unavailable. This revises the unpublished seed's
`pass_fds` and `fd` fields before A freezes the interface.

```text
ExecutionSupport:
    setup(api: GoalSetupAPI) -> None
    environment_removals -> frozenset[str]
    open(event: PreparedCallEvent, api: GoalAPI,
         platform_support: ExecutionPlatformSupport) -> ExecutionSession | None

ExecutionSession:
    launch -> ExecutionLaunch
    spawned(pid: int) -> None
    interests() -> tuple[ExecutionInterest, ...]
    step(ready: tuple[ExecutionReady, ...]) -> ExecutionProgress
    stop(reason: ExecutionEndReason) -> None
    close(end: ExecutionEnd) -> None
```

| Record | Frozen keyword-only fields |
| --- | --- |
| `ExecutionPlatformSupport` | `implemented: bool`, `reason: str \| None`, `binding_ids: frozenset[str]`; unavailable means a nonempty reason and no bindings |
| `ExecutionLaunch` | Copied immutable `environment: Mapping[str, str]`, `attachments: tuple[ExecutionLaunchAttachment, ...]` |
| `ExecutionInterest` | `resource: ExecutionWaitResource`, `readable: bool`, `writable: bool`; at least one event requested |
| `ExecutionReady` | `resource: ExecutionWaitResource`, `readable: bool`, `writable: bool`; strategy-generated readiness for an actual requested resource |
| `ExecutionProgress` | `immediate: bool`, requesting a nonblocking next turn after child polling |
| `ExecutionEnd` | `reason: ExecutionEndReason`, `outcome: CallOutcome \| None`; no invented outcome for failed preparation/termination before a result |

`ExecutionEndReason` contains `PREPARATION_FAILED`, `SPAWN_FAILED`, `CHILD_EXIT`,
`INFRASTRUCTURE_FAILED`, and `TERMINATION`. `ExecutionSupportUnavailableError` is a
typed runtime error. `EXECUTION_SUPPORT_API_MAJOR = 1` describes definitions;
`EXECUTION_SUPPORT_IMPLEMENTED = False` in A's concrete wrapper describes reality.

The new constructor argument is keyword-only, `execution_support=None`. A rejects
any other value immediately without reading helper properties or invoking methods.
B freezes/validates launch environment names and values and unique attachment and
interest identities. Its execution strategy validates the native binding, session
ownership and liveness. The session owns its endpoint resources; the wrapper owns
waiting and the process through the strategy, with idempotent attachment cleanup
as a backstop. No child process handle, raw plugin dispatcher, or implementation
object enters this interface.

Two new abstract resource interfaces also belong to A:

```text
ExecutionLaunchAttachment:
    close() -> None                           # idempotent owned-resource release

ExecutionWaitResource:
    # Opaque session-bound object identity; no native fields or fileno contract.
```

These are local handles, not serializable records. Platform-specific subtypes and
their implementations are B work. Generic code never casts them to integers or
derives OS operations from their fields. An attachment's immutable public identity
can refer to changing internal open/closed ownership state. `close()` invalidates
ownership before release and cannot dispatch providers or access callback APIs.

`platform_support` is an immutable snapshot supplied by the wrapper from its
selected strategy. The helper checks its binding ID against `binding_ids` before
allocating transport resources. It receives no process-owning strategy methods.
There is no extra public strategy constructor argument in A. API importability,
generic wrapper support implementation, native strategy availability and broker
selection remain distinct facts.

## Method lifetime

`setup` receives only a setup-window API. `open` is inside the goal's active achieve
window, receives the strategy support snapshot, and owns self-unwind if it fails
before returning a session. Session methods run on that same thread and within
that same achieve window. A services session
may retain its callback-bound goal operation client until close; it cannot use it
from a worker, another callback or after the session ends.

`spawned` runs once after successful native spawn, including if the child exited
quickly. Release redundant child-side host resources there; the wrapper must still release them
on notification failure. `stop` is idempotent, revokes ingress and closes transport
without running provider cleanup. `close` is idempotent, releases scope resources
and always invalidates the session even if cleanup raises. It follows preparation
unwind or process reaping/signal restoration as applicable.

If `stop` or `close` raises, the wrapper still attempts remaining process, resource
and signal cleanup. First termination has propagation precedence. Generic wrapper failures
need the generic failure-reporting path discussed in
[process lifetime](process/README.md). Its compatibility with the real `GoalResult`
is still a pre-freeze gate; the strategy change does not resolve that separate gap.
