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
    pre_after_value = None
    try:
        create handlers, recording successful construction
        result, entered = run_before_hooks()
        if no early result: result = run_goal()
        pre_after_value = result.value  # capture before outer hooks can replace it
        # Managed failure reporting uses the accumulator, never exception-valued result.error.
        result = run_entered_after_hooks(result)
    except BaseException as primary:
        failures.capture_primary(primary)
    finally:
        for handler in reverse(created_handlers):
            failures.attempt(close_once(handler, fresh OperationAPI(caller=None)))
        for destruction in queued_destructions_in_stable_order:
            failures.attempt(destruction)
        for api in all_participant_apis_and_goal_api:
            failures.attempt(api.close)

    if failures.has_termination: raise failures.first_termination
    if failures.has_managed_defect or failures.has_workspace_cleanup_failure:
        return GoalResult(
            status=FRAMEWORK_FAILED, exit_code=70,
            value=pre_after_value,
            error=failures.primary_framework_error_text, ...
        )
    return existing_result_or_exception_behavior(result, failures)
```

The pseudocode factors existing boundary handling for clarity; it does not prescribe
swallowing ordinary goal exceptions until the end. Existing goal/framework result
translation and entered-hook semantics remain. An application that never uses
operations does not gain a universal sticky failure rule. Registered-but-unused
operations do not themselves turn ordinary hook result transformations into defects.

Retain the pre-after-goal result value separately from the mutable result pipeline.
On a managed failure, returning the latest hook's value is insufficient: a hook
could replace the result with `GoalResult.completed()` and discard the real child
outcome while exit 70 remains latched. Capture a returned goal result inside the
goal boundary before deactivation can fail. Successful ordinary invocations still
use the existing after-hook transformations; the saved value is for managed-failure
reporting, not a universal prohibition on result changes.

Wrapper failures outside operation handlers still require an explicit generic
goal-side reporting boundary. The old draft's exception-valued `GoalResult.error`
was invalid and has been withdrawn; see the
[pre-freeze contract gap](../../executable-support/process/README.md#preserving-the-real-outcome-and-the-failure-latch).
The accumulator algorithm alone does not define that missing public path.

### Capturing callback outcomes before cleanup

```text
call_owner(owner, phase, event):
    primary = none; value = none; activation_started = false
    try:
        begin owner activation; activation_started = true
        push owner frame
        value = owner.endpoint.dispatch_phase(phase, event, owner_api)
        validate contribution while owner is active
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

## Outcome examples

| Situation | Result |
| --- | --- |
| Provider returns declared `inventory_unavailable`; sleep aborts safely | Domain-selected nonzero command result, no managed latch |
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
