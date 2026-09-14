# Process ownership and pump lifecycle

Back to [executable support](../README.md). Evidence:
[current wrapper lifecycle](../../evidence.md#executable-wrapper).

OS mechanisms below belong to the [execution strategy](../strategies/README.md).
The generic loop owns sequencing and deals in opaque launch/wait resources. Linux
implements the existing process behavior; Windows is explicitly unavailable.

## Ordered lifecycle

| Point | Required behavior |
| --- | --- |
| Setup | Helper setup after help collection; no sockets or child |
| Help/completion/preemption | Preserve existing behavior; no `open`, no child service session |
| Surviving normal call | `open` before preparation; open self-unwinds on failure |
| Preparation | Existing one-plugin-at-a-time dispatch; only successful preparers enter reverse unwind |
| Preparation failure | Preparer's own unwind, successful preparers' reverse `prepare_failed`, then session stop/close; no `after_call` |
| Spawn failure | Narrow executable-resolution/`Popen` translation to 127/126; stop/close session, dispatch real `SPAWN_FAILED` outcome |
| Spawn success | Wrapper retains the only strategy-owned process; strategy attaches signal forwarding, then helper gets PID and pump starts |
| Child exit | Stop ingress, reap, restore temporary signal handlers, close child resources, then `after_call` with actual outcome |
| Ordinary infrastructure defect | Revoke transport, retain managed failure, continue waiting/reaping the child; no automatic child kill |
| Termination in helper/provider | Stop ingress, terminate the direct child, reap, restore signals, exhaust cleanup, re-raise first termination |

Service scope closure happens after successful preparer unwind on preparation
failure so preparers can still use invocation-local services during their release.
Child scope resources are separate and close before any ordinary `after_call`.

## Pump pseudocode

```text
owned_launch = strategy.prepare_launch(snapshot_launch, session_owner)
process = strategy.spawn(...)                # only native resolution/spawn maps 127/126
try:
    signal_restoration = strategy.attach_signals(process)
    session.spawned(process.pid)
    immediate = true
    while process.poll() is None:
        interests = session.interests()
        timeout = 0 if immediate else at_most_100_ms
        ready = strategy.wait(interests, timeout, session_owner)
        if process.poll() is not None: break
        progress = session.step(ready)        # step(()) also advances timers
        if process.poll() is not None: break
        immediate = progress.immediate
except Exception as error:
    record managed execution failure preserving any existing OperationFailure
    attempt session.stop(INFRASTRUCTURE_FAILED)
    process.wait()                           # existing ordinary process semantics
except BaseException as termination:
    preserve first termination
    attempt session.stop(TERMINATION)
    process.terminate_and_reap()              # native escalation is strategy-owned
finally:
    exhaust endpoint, launch, process, wait, signal and session cleanup
```

The helper's bounded step may perform one synchronous top-level service dispatch.
Nested providers can take arbitrarily long until they cooperate. The 100 ms bound
limits strategy waits, not callback execution or overall shutdown. Poll once more
before writing a response created by provider work; discard it if the child exited.

Only Ctrl-C raised in the wrapper's designated wait region gets the existing
forward-and-continue treatment. A `KeyboardInterrupt` raised by `session.step` or
a provider follows the termination branch. Never kill the shared process group;
the direct child shares the controlling terminal/process-group behavior by design.

## Preserving the real outcome and the failure latch

A gap in the seed contract is that wrapper infrastructure can fail outside an
operation handler. It still needs a managed failure marker without importing
services or adding a general sticky result policy.

The earlier draft placed `OperationFailure` directly in `GoalResult.error`. That
proposal is invalid: the [real API](../../../../engulf-api/src/engulf_api/goals.py#L29)
requires `str | None` and rejects an exception object. Do not copy that pseudocode
into implementation or widen the existing field implicitly.

The required behavior remains:

```text
after_call receives actual CallOutcome(exit_code=child_exit, ...)

if execution_failure exists:
    record failure in core's accumulator through an explicit goal-side boundary
        # PRE-FREEZE GAP: this boundary still needs a concrete generic API contract.
    return GoalResult(status=FRAMEWORK_FAILED, exit_code=70,
                      value=actual_outcome, error=bounded_error_text)
```

If the failure already came from a managed provider, keep that carrier unchanged
in the internal accumulator. Failure identity must be independent of whether a
requestable operation/handler exists; do not fabricate a registered operation.
Plain failed results and unrelated exceptions retain existing semantics. If
`after_call` itself raises while an execution failure is pending, preserve/report
the execution carrier and the after-call failure without losing the actual outcome.
Concretely, capture the after-call exception, retain it as a secondary diagnostic,
and return a failed result with the real outcome and textual error. A termination
still propagates after cleanup. Without a pending managed failure, retain the
existing after-call exception behavior.

Resolving that goal-side reporting API is an explicit A freeze gate, separate from
the platform-strategy decision. Tests must use real `GoalResult` objects and
exercise the path with a generic fake helper, with no services installed, and with
an outer hook that attempts to return success.
The wrapper must validate that the failure arose on an enabled support path;
ordinary process exit codes do not create managed defects.

## Recursive review

Inject failures into `open`, strategy binding/launch validation, `spawned`, wait setup,
`interests`, `step`, `stop`, `close`, preparer self-unwind and another preparer's
unwind. Assert one process owner, no zombies, all descriptors closed, real
`after_call` outcome, no after-call for failed preparation, original termination,
and no support methods called on the disabled path. Use pipes/barriers and PTY
tests; do not infer signal behavior from a mocked `wait()` alone.
