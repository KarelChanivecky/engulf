# Generic contracts reserved in A

Back to [managed operations](README.md). All new records are frozen and keyword-only;
collections are defensively copied to immutable forms. All public imports are from
`engulf_api`. API packages remain dependency-free and typed.

## Definitions

| Definition | Fields or behavior |
| --- | --- |
| `MANAGED_OPERATIONS_API_MAJOR` | Integer `1`; definition compatibility only |
| `OperationSupport` | `api_major: int`, `implemented: bool`, `reason: str \| None`; unavailable requires a nonempty reason, implemented requires `None` |
| `OperationCallerKind` | Enum `GOAL`, `PLUGIN`; **refinement added to the seed proposal** |
| `OperationCallFrame` | `participant_id: str`, `participant_kind: OperationCallerKind`, `phase_id: str`, `operation_id: str`; runtime-derived immutable diagnostic/authority facts |
| `InvocationOperation[R, S]` | `operation_id: str`, `request_type: type[R]`, `response_type: type[S]`, `phases: tuple[GoalPhase, ...]`, `handler_factory: Callable[[Invocation], OperationHandler[R, S]]` |
| `OperationHandler[R, S]` | `handle(request: R, api: OperationAPI) -> S`; `close(api: OperationAPI) -> None` |
| `OperationClient` | Read-only `support: OperationSupport`; `request(operation_id: str, request: object) -> object` |
| `GoalSetupAPI` additions | Read-only `operation_support`; `register_operation(definition) -> None`; concrete unsupported defaults |
| `InvocationAPI` addition | Read-only `operations: OperationClient`; concrete unsupported default |
| `GoalAPI` addition | `report_managed_failure(error: Exception, *, stage: str) -> None`; concrete unsupported default in A |

Records use dataclasses; `OperationCallerKind` is an enum. `OperationClient`,
`OperationHandler` and `OperationAPI` are nominal ABCs, not structural protocols.
`handle` is abstract; handler `close` has a concrete no-op default. Future optional
ABC members need concrete defaults. No per-invocation start callback is reserved:
construction is data-only and activated initialization occurs on the first request.

Keep the read-only support properties: they describe implementation availability,
not registration, target readiness or authorization. An operation-specific query,
if a consumer later needs one, is a separate additive method; changing a property's
meaning is not the extension mechanism. Defaulted record fields can be added without
changing these signatures. Closed error codes require compatibility review; callers
must handle an unknown code as a request rejection, never as a managed defect.

Use the repository's identifier validation for operation IDs. The reserved goal
participant ID is runtime metadata and is not validated as a normal plugin ID.
The caller-kind field avoids coupling a service control decision to a string prefix
or a caller-supplied identifier. No `CHILD` kind is added to core: a child is an
origin inside the services handler, reached by the actual goal's managed request.

`InvocationOperation` construction validates a real request/response class, tuple of
`GoalPhase` instances, unique phase IDs, and callable factory. It cannot inspect
Python generic arguments to determine a phase's API kind. The supported adapter
contract uses invocation APIs; the runtime always supplies one. See
[canonical dispatch](dispatch/README.md).

## Restricted handler API

```text
OperationAPI extends diagnostics/application metadata:
    operation_id: str
    invocation: Invocation
    caller: OperationCallFrame | None
    call_chain: tuple[OperationCallFrame, ...]
    cleanup_deadline: float | None
    dispatch(phase, event, *, plugin_ids: Sequence[str]) -> tuple[AttributedContribution, ...]
    report_failure(failure: OperationFailure) -> None
```

The API exposes no provider implementation, context/state store, lease factory,
arbitrary operation registry, process object, or caller identity setter. It is a
fresh, thread-bound window for each `handle` or `close`, including reentrant calls
into the same handler. `caller` is absent only for core finalization. It is present
for explicit goal-driven child-scope close. A retained outer handler API cannot be
used while a provider or nested handler is current.

`cleanup_deadline` is the host monotonic absolute deadline during core-driven handler
finalization, including nested windows of that closing operation, and `None` during
ordinary handling. Services cap their close budgets by it. Explicit child-scope
close during normal goal work starts a service-owned budget; any later finalization
uses the earlier of the scope's existing deadline and this core deadline. This is
a cooperative deadline, not permission to skip mandatory release attempts.

`dispatch` requires target IDs and the exact registered phase object. Core validates
selection, entered status, current stack and lock order before endpoint execution.
`report_failure` accepts a failure belonging to the current operation; it preserves
runtime-minted origin/chain and records it in the invocation's accumulator. A public
`OperationFailure` constructor does not mint provenance: an unrecognized carrier is
rejected as `invalid_request`, without accepting its claimed origin or chain.
Handwritten caller frames cannot authorize dispatch. The runtime constructs the
authoritative chain regardless of public record construction.

## Errors

| Error | Contract |
| --- | --- |
| `OperationUnavailableError(RuntimeError)` | `feature`, `reason`; definition is unavailable in this runtime, not a provider defect |
| `OperationRequestError(RuntimeError)` | Stable `code`, safe `message`, optional runtime-derived `target_id`, immutable `call_chain` |
| `OperationFailure(RuntimeError)` | `operation_id`, `stage`, `error: Exception`, `origin: PluginCallbackError \| None`, immutable `call_chain` |

Closed request codes are `invalid_request`, `unknown_operation`, `invalid_target`,
`target_not_ready`, `call_cycle`, `call_depth_exceeded`, and `lock_order`. They do
not latch managed failure. Service-specific access, deadline or resource errors
belong to services, not this core list. A request to a different operation during
core finalization is `invalid_request` with an explanatory message.

`OperationFailure` is the generic carrier preserved through phase, before/after
hook and goal boundaries. Keep existing `PluginCallbackError` fields and constructor
unchanged. `stage` identifies creation, handling, dispatch or cleanup in diagnostics;
it is not a service wire error kind. Only `Exception` is wrapped. Termination
exceptions are recorded separately and propagated after cleanup.

## Goal-side reporting and provenance

`GoalAPI.report_managed_failure(error, *, stage)` is the proposed replacement for
R37. It returns no carrier. B requires the invoking thread and the actual current
goal frame, validates an `Exception` and a dot-qualified stage identifier, and
records the failure before returning. A and old custom GoalAPI subclasses raise
`OperationUnavailableError`; there is no A latch or success-shaped reporting stub.

For an ordinary error core derives the goal owner and current call chain itself.
The wrapper uses stage labels under
`org.engulf.executable-wrapper.execution-support`, such as `.open` and `.close`;
these are diagnostics, not operation registrations or authorization identities.
For an authentic `OperationFailure` minted by this invocation, preserve its original
provider attribution and deduplicate the already recorded failure. Core validates
private invocation-bound provenance, not public `origin`/`call_chain` fields or
matching identifiers. An unrecognized or foreign carrier passed here is an error
attributed to the current goal; its asserted provider identity is never trusted.
Provenance travels with the runtime carrier, so no unbounded identity registry is
needed. This protects attribution for cooperating code, not hostile Python with
the same process authority.

`GoalResult.error` remains `str | None`; no returned result is a reporting channel.
Before-goal short circuits and after-goal replacement results cannot mint a latch
or provider blame. Plugins cannot report through an ancestor's goal API while their
own frame is current. Genuine provider failures are already recorded by dispatch.

Preserve values with the existing public `GoalResult` constructor. Adding `value`
to `framework_failed()` is unnecessary; B changes the relevant failure-merging
sites, not every existing use of that classmethod. See
[lifecycle](lifecycle/README.md) and [wrapper reporting](../executable-support/process/README.md).
This contract is specified for A but remains gated on real typed API consumers and
the B behavior tests; documentation alone does not discharge those gates.

## Definition vs implementation validation

A validates these immutable definitions and supplies the unavailable implementations
described in [foundation](../foundation/stubs.md). B additionally proves current
frames, selected/entered dispatch, locks, failure precedence and cleanup. Neither a
major constant nor a protocol's structural conformance substitutes for those tests.
