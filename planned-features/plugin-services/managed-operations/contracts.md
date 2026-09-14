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
    dispatch(phase, event, *, plugin_ids: Sequence[str]) -> tuple[AttributedContribution, ...]
    report_failure(failure: OperationFailure) -> None
```

The API exposes no provider implementation, context/state store, lease factory,
arbitrary operation registry, process object, or caller identity setter. It is a
fresh, thread-bound window for each `handle` or `close`, including reentrant calls
into the same handler. `caller` is absent only for core finalization. It is present
for explicit goal-driven child-scope close. A retained outer handler API cannot be
used while a provider or nested handler is current.

`dispatch` requires target IDs and the exact registered phase object. Core validates
selection, entered status, current stack and lock order before endpoint execution.
`report_failure` accepts a failure belonging to the current operation; it preserves
validated runtime origin/chain and records it in the invocation's accumulator.
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

A goal can also return a `GoalResult` whose `error` is an explicit `OperationFailure`.
Core records that carrier before outer hooks, preserving the result value. The
wrapper uses the reserved failure identity
`org.engulf.executable-wrapper.execution-support` for defects in its enabled generic
support seam that occur outside a registered handler. This identity is not a
requestable operation. Outside an existing operation chain, the goal supplies an
empty chain and core attributes the result boundary from its own current frame.
An ordinary failed goal result does not acquire this behavior. See the
[wrapper refinement](../executable-support/process/README.md).

## Definition vs implementation validation

A validates these immutable definitions and supplies the unavailable implementations
described in [foundation](../foundation/stubs.md). B additionally proves current
frames, selected/entered dispatch, locks, failure precedence and cleanup. Neither a
major constant nor a protocol's structural conformance substitutes for those tests.
