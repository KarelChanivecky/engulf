# Invocation lifetime and failure precedence

Back to [managed operations](../README.md).

## State machine

```text
UNCREATED -> CREATING -> RUNNING -> CLOSING -> CLOSED
                  failure ------> CLOSING
```

Definitions live with the Application after setup; each invocation creates fresh
handlers before the first outer hook. Factories receive immutable `Invocation`, no
API, and must not depend on activated providers. Construct handlers in registration
order. If a factory fails, close every earlier-created handler in reverse order;
the failed factory owns unwinding any partial construction it did itself.

`close` executes at most once per created handler. Mark it closing before invocation,
and closed in an unconditional finalizer. During core finalization, nested calls
are limited to the current closing operation; services then further restrict them
to established dependency edges. New handlers, other operations and new scopes
cannot be opened. Handler close may dispatch only entered owners.

## Failure accumulator

Use a small **internal** accumulator, not a new public exception hierarchy or a
general result-transform policy. It retains the first termination exception, the
first actual managed defect, and ordered secondary diagnostics. Deduplicate the
same propagated `OperationFailure`. Do not retain arbitrary payloads or unbounded
trace histories. Existing workspace-cleanup failure precedence remains enforced.
Retain at most 32 secondary failure records plus a count of omitted records; log
secondary failures through managed diagnostics as they occur. The first managed
defect and first termination are never evicted. Bound deduplication bookkeeping too,
rather than accumulating every failure identity during a long polling invocation.

```text
invoke_with_managed_operations(invocation):
    failures = FailureAccumulator()
    result = no_result
    saved_value = None
    # Both callbacks below run immediately after result validation, inside entry/exit.
    capture_early_result(validated): saved_value = validated.value
    capture_goal_result(validated): saved_value = validated.value
    try:
        create handlers, recording successful construction
        result, entered = run_before_hooks(on_early_result=capture_early_result)
        if no early result:
            result = run_goal(on_validated_result=capture_goal_result)
        # Capture precedes goal/early-hook deactivation, lock release and frame pop.
        result = run_entered_after_hooks(result)
    except BaseException as primary:
        failures.capture_primary(primary)
    finally:
        cleanup_deadline = monotonic_now() + aggregate_cleanup_budget
        for handler in reverse(created_handlers):
            failures.attempt(lambda: close_once(handler,
                fresh OperationAPI(caller=None, cleanup_deadline=cleanup_deadline)))
        for outcome in state_manager.iter_destruction_outcomes():
            failures.record_workspace_outcome(outcome)
        for api in all_participant_apis_and_goal_api:
            failures.attempt(api.close)
        emit_unused_context_warning_using_existing_result_predicate(result)

    if failures.has_termination: raise failures.first_termination
    if failures.has_managed_defect or failures.has_cleanup_failure:
        return GoalResult(
            status=FRAMEWORK_FAILED, exit_code=70,
            value=saved_value,
            error=failures.primary_framework_error_text, ...
        )
    return existing_result_or_exception_behavior(result, failures)
```

The pseudocode factors existing boundary handling for clarity; it does not prescribe
swallowing ordinary goal exceptions until the end. Existing goal/framework result
translation and entered-hook semantics remain. An application that never uses
operations does not gain a universal sticky failure rule. Registered-but-unused
operations do not themselves turn ordinary hook result transformations into defects.

`iter_destruction_outcomes` is a proposed internal state-manager refactor, not an
existing API. It snapshots queued targets in stable order, attempts each separately,
catches each ordinary error or termination, and yields its attributed outcome.
Application consumes every outcome and feeds the accumulator explicitly. Today's
`finalize_destructions()` returns ordinary failure records and can terminate early;
wrapping that call with `attempt()` would neither consume those records nor provide
the required exhaustive behavior. The existing tuple-returning internal entry point
can share this primitive, but Application must not discard yielded failures.
`failures.attempt` invokes its supplied callable immediately inside its own guarded
boundary; do not evaluate a closer before passing it to the accumulator. Recording
or rendering a secondary diagnostic must not stop traversal of later finalizers.

If workspace cleanup is the only defect, the final error text remains
`workspace state cleanup failed`. With an earlier managed defect, keep its text as
primary and emit the workspace failures as attributed secondaries. Termination has
precedence over either result. `saved_value` is the validated early result's value
when no goal ran, the validated goal value otherwise, or `None` if neither existed.

Retain the pre-after-goal result value separately from the mutable result pipeline.
On a managed failure, returning the latest hook's value is insufficient: a hook
could replace the result with `GoalResult.completed()` and discard the real child
outcome while exit 70 remains latched. Capture a returned goal result inside the
goal boundary before deactivation can fail. Successful ordinary invocations still
use the existing after-hook transformations; the saved value is for managed-failure
reporting, not a universal prohibition on result changes.

Wrapper failures outside operation handlers use the proposed
[`GoalAPI.report_managed_failure`](../contracts.md#goal-side-reporting-and-provenance).
`GoalResult.error` remains textual. Final failure merging uses the public constructor
that already accepts a value; `framework_failed()` need not change.

### Capturing callback outcomes before cleanup

```text
# This is the shared boundary inside engulf._dispatch, not another dispatcher.
run_participant_callback(owner, phase, invoke_endpoint, on_validated_result=None):
    primary = none; value = none; activation_started = false
    try:
        begin owner activation; activation_started = true
        push owner frame
        value = invoke_endpoint(owner_api)       # hook, goal, or phase endpoint
        validate contribution while owner is active
        if on_validated_result: on_validated_result(value)
    except BaseException as error:
        primary = error
    finally:
        attempt all owner-local lock releases and API deactivation
        pop any frame actually pushed
        preserve primary; collect cleanup failures separately
    return value or propagate the preserved failure
```

If termination occurs during cleanup after an ordinary primary error, termination
takes propagation precedence; retain the ordinary error diagnostically. If multiple
termination exceptions occur, preserve the first. Cleanup errors cannot replace C's
origin with B's or mask the first termination. Apply the same exhaustive discipline
to state destruction and API-close loops; a bare `finally` around a sequence of
unguarded finalizers is insufficient.

### B compatibility and interruption policy

B1 applies the shared callback boundary to existing invocations too. B-COMPAT must
cover these deliberate cleanup changes with no operations registered:

- deactivation cannot mask the callback's primary error;
- one failing API close or workspace destruction no longer skips later finalizers;
- cleanup failure yields framework exit 70 with the saved goal/early-result value;
- `UnusedContextWarning` uses the existing predicate: the last normal result exists
  and is `COMPLETED`, evaluated independently of the final failure overlay;
- ordinary hook result replacement, plugin entry rules and successful results stay
  as before; registered-but-unused operations do not create a sticky failure.

Finalization has one absolute cooperative budget (initially 30 seconds); each scope
close receives at most five seconds and the remaining total. Dependencies inherit
that remaining budget. After exhaustion, every remaining finalizer is still attempted
with an expired deadline and must use immediate best-effort release and its own
recovery journal. Core cannot synthesize journals for arbitrary external resources.
These budgets constrain cooperative waits, not synchronous Python execution.
The handler receives the deadline through `OperationAPI.cleanup_deadline`; services
derive close-event budgets from it. Ordinary state cleanup and lock-release system
calls may still exceed it. There is no new promise of interruptible filesystem work.

The exhaustive-cleanup requirement is retained: a second `KeyboardInterrupt` is
recorded and does not abandon remaining finalizers. Report that finalization is still
running and re-raise the first termination afterward. This is an explicit behavioral
change from today's interruptible close loop, not a hard shutdown guarantee. An
abort-on-second-interrupt mode would relax the cleanup requirement and is deferred;
test repeated termination and budget exhaustion without promising forced cancellation.

## Outcome examples

| Situation | Result |
| --- | --- |
| Provider returns declared `inventory_unavailable`; reclaim aborts safely | Domain-selected nonzero command result, no managed latch |
| Provider C crashes; A catches the failure and returns success | Framework exit 70 after outer hooks/cleanup, origin C preserved |
| Child exits 2 after an ordinary transport infrastructure failure | `after_call` sees real exit 2; outer `GoalResult` ends framework-failed 70 and retains the `CallOutcome` |
| Provider raises `KeyboardInterrupt`; one closer also fails | Attempt every close/destruction/API release, then propagate the first termination |
| A before-goal consumer completes early | Finalize handlers even though `goal.achieve` and later before hooks never ran |
| No managed work; an existing hook transforms an ordinary result | Preserve existing behavior; do not introduce a universal latch |

## Recursive review and remaining limits

No resource finalizer can guarantee completion if arbitrary in-process code never
returns or the process is killed. Capability owners still need idempotent release,
finite waits and durable recovery for external resources. Factory construction
should be data-only; generic finalization cannot close an object that was never
returned. Cross-operation cleanup dependencies are deliberately unsupported; place
related resources in one handler. The services scope manager supplies the one DAG
that the concrete use cases require.
